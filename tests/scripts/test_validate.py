"""Unit tests for module validate"""
from pathlib import Path
from unittest.mock import patch

import pytest

from build import package_skill
from skilllib import discover, load
from tests.mocks import DEEPLY_NESTED_JSON, add_symlink_loops, fm, make_skill, symlink_or_skip
from validate import _check_links, _local_links, check_skill, main


def errors_of(skill_dir: Path) -> list[str]:
    """Run check_skill on one skill and return only its errors"""
    return check_skill(skill_dir, {})[0]


def contains(errors: list[str], text: str) -> bool:
    """Whether any error message contains the text"""
    return any(text in e for e in errors)


def test_check_skill_valid_skill(tmp_path):
    """Happy path"""
    assert errors_of(make_skill(tmp_path, "good-skill")) == []


def test_check_skill_one_bad_skill_does_not_stop_later_skills(tmp_path):
    """Every skill is checked, whatever is wrong with the ones before it"""
    bad = make_skill(tmp_path, "bad", frontmatter="name: bad\nmetadata: nope\ndescription: x\n", evals=[1])
    good = make_skill(tmp_path, "good")
    seen: dict = {}
    assert check_skill(bad, seen)[0]
    assert check_skill(good, seen)[0] == []


def test_check_skill_invalid_yaml(tmp_path):
    """Invalid YAML is a finding, not an exception"""
    skill = make_skill(tmp_path, "broken", frontmatter="name: broken\ndescription: a: b: c\n  bad: [\n")
    assert contains(errors_of(skill), "invalid YAML")


def test_check_skill_numeric_name(tmp_path):
    """A name that YAML reads as a number is rejected"""
    skill = make_skill(tmp_path, "123", frontmatter="name: 123\ndescription: Use when testing.\n")
    assert contains(errors_of(skill), "name must be a string")


def test_check_skill_non_string_description(tmp_path):
    """A description that YAML reads as a number is rejected"""
    skill = make_skill(tmp_path, "num-desc", frontmatter="name: num-desc\ndescription: 42\n")
    assert contains(errors_of(skill), "description must be a string")


@pytest.mark.parametrize("test_input", ["just-a-string", "[a, b]"])
def test_check_skill_non_mapping_metadata(test_input, tmp_path):
    """Scalar and list metadata are findings, not exceptions"""
    skill = make_skill(tmp_path, "meta", frontmatter=fm("meta", f"metadata: {test_input}\n"))
    assert contains(errors_of(skill), "metadata must be a mapping")


@pytest.mark.parametrize(
    "test_input",
    ["null", "[1, 2]", "abc", "1.5", '"²"', '"-1"', '"١٢"', '""', '" 5"'],
    ids=["null", "list", "text", "float", "superscript", "negative", "arabic-indic", "empty", "leading-space"],
)
def test_check_skill_malformed_order(test_input, tmp_path):
    """Only ASCII digits are a valid order; str.isdigit() would accept the superscript and Arabic-Indic digits"""
    skill = make_skill(tmp_path, "ordered", frontmatter=fm("ordered", f"metadata:\n  order: {test_input}\n"))
    assert contains(errors_of(skill), "metadata.order")


def test_check_skill_valid_order(tmp_path):
    """Happy path - a quoted string of ASCII digits"""
    skill = make_skill(tmp_path, "ok-order", frontmatter=fm("ok-order", 'metadata:\n  order: "007"\n'))
    assert errors_of(skill) == []


def test_check_skill_non_object_eval_entry(tmp_path):
    """Entries that are not objects are findings, not exceptions"""
    skill = make_skill(tmp_path, "bad-evals", evals=["a string", 5, {"id": "x", "query": "q", "expected_behavior": ["b"]}])
    assert sum("must be an object" in e for e in errors_of(skill)) == 2


def test_check_skill_link_inside_the_skill(tmp_path):
    """Happy path"""
    skill = make_skill(tmp_path, "inside", body="See [ref](references/a.md).\n", files={"references/a.md": "# A\n"})
    assert errors_of(skill) == []


@pytest.mark.parametrize("test_input", ["../outside.md", '../outside.md "Details"'], ids=["plain", "titled"])
def test_check_skill_link_outside_the_skill(test_input, tmp_path):
    """A link that leaves the skill directory would be missing once packaged"""
    (tmp_path / "outside.md").write_text("x", encoding="utf-8")
    skill = make_skill(tmp_path, "escaper", body=f"See [other]({test_input}).\n")
    assert contains(errors_of(skill), "outside the skill directory")


def test_check_skill_titled_link_to_existing_file(tmp_path):
    """A link with a title still counts as linking the reference"""
    skill = make_skill(tmp_path, "titled-ok", body='See [ref](references/a.md "Details").\n', files={"references/a.md": "# A\n"})
    errors, warnings = check_skill(skill, {})
    assert errors == []
    assert warnings == []


def test_check_skill_titled_link_to_missing_file(tmp_path):
    """A link with a title is still checked"""
    skill = make_skill(tmp_path, "titled-missing", body='See [ref](references/missing.md "Details").\n')
    assert contains(errors_of(skill), "missing file 'references/missing.md'")


@pytest.mark.parametrize("test_input", ["evals/evals.json", "references/evals/x.json", "scripts/__pycache__/m.pyc"])
def test_check_skill_link_into_a_directory_that_is_not_packaged(test_input, tmp_path):
    """Packaging leaves evals and caches out, so a link into them would be missing"""
    skill = make_skill(tmp_path, "into-ignored", body=f"See [x]({test_input}).\n", files={test_input: "{}"})
    assert contains(errors_of(skill), "not packaged")


def test_check_skill_unreadable_reference(tmp_path):
    """The bad reference is reported and the next skill is still checked"""
    bad = make_skill(tmp_path, "bad-ref", body="See [r](references/bad.md).\n", files={"references/bad.md": b"\xff\xfe invalid utf-8"})
    good = make_skill(tmp_path, "good-after")
    seen: dict = {}
    bad_errors, _ = check_skill(bad, seen)
    assert any("cannot read reference" in e and "bad.md" in e for e in bad_errors)
    assert check_skill(good, seen)[0] == []


def test_check_skill_symlinks(tmp_path):
    """Every symlink in a packaged path is reported, including a link to a directory"""
    skill = make_skill(tmp_path, "linked", files={"references/real.md": "# R\n"})
    symlink_or_skip("real.md", skill / "references" / "alias.md")
    symlink_or_skip("references", skill / "refs-dir")
    assert sum("symlinks are not allowed" in e for e in errors_of(skill)) == 2


def test_check_skill_symlinked_references_directory_is_not_read(tmp_path):
    """The link is reported and nothing behind it is read, however large or broken the target tree is"""
    external = tmp_path / "external"
    (external / "deep").mkdir(parents=True)
    (external / "bad-bytes.md").write_bytes(b"\xff\xfe invalid utf-8")
    (external / "deep" / "long.md").write_text("line\n" * 150, encoding="utf-8")
    (external / "deep" / "broken.md").write_text("See [x](missing.md).\n", encoding="utf-8")
    skill = make_skill(tmp_path / "skills", "linked-refs")
    symlink_or_skip(str(external), skill / "references")
    reads: list[Path] = []
    original_read_text = Path.read_text

    def spy(self, *args, **kwargs):
        reads.append(self)
        return original_read_text(self, *args, **kwargs)

    with patch.object(Path, "read_text", spy):
        errors = errors_of(skill)
    assert contains(errors, "symlinks are not allowed")
    assert not contains(errors, "cannot read reference")  # the bad bytes behind the link were never opened
    assert not contains(errors, "Contents")
    assert [p for p in reads if external in p.parents or p == external] == []


def test_check_skill_symlink_loops(tmp_path):
    """Loops are reported without raising RuntimeError, and later skills are still checked"""
    looped = make_skill(tmp_path, "looped", body="See [a](references/loop.md) and [b](references/a.md).\n")
    add_symlink_loops(looped)
    good = make_skill(tmp_path, "good-after-loop")
    seen: dict = {}
    errors, _ = check_skill(looped, seen)
    assert contains(errors, "symlinks are not allowed")
    assert check_skill(good, seen)[0] == []


def test_check_skill_symlinked_skill_and_domain_roots(tmp_path):
    """A symlinked skill directory or domain directory is rejected before anything is read through it"""
    skills = tmp_path / "skills"
    real = make_skill(tmp_path / "real", "outside-skill")
    (skills / "dom").mkdir(parents=True)
    symlink_or_skip(str(real), skills / "dom" / "linked-skill")
    real_domain = tmp_path / "real-domain"
    make_skill(real_domain, "domain-skill")
    symlink_or_skip(str(real_domain), skills / "linked-domain")
    found = discover(skills)
    assert len(found) == 2  # discover sees both, so validation has to reject them
    by_label = {f"{d.parent.name}/{d.name}": errors_of(d) for d in found}
    assert contains(by_label["dom/linked-skill"], "skill directory must not be a symlink")
    assert contains(by_label["linked-domain/domain-skill"], "domain directory must not be a symlink")


@pytest.mark.parametrize(
    "test_input, expected",
    [
        ("evals/link.json", False),
        ("__pycache__/x.pyc", False),
        ("references/evals/link.json", False),
        ("references/__pycache__", False),  # a file link that is named like an ignored name
        ("references/link.md", True),
        ("link.md", True),
    ],
)
def test_check_skill_rejects_exactly_the_symlinks_that_packaging_follows(test_input, expected, tmp_path):
    """Packaging follows links, so a link is rejected exactly when it would end up in the packaged output"""
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    skill_dir = make_skill(tmp_path / "skills" / "d", "agree")
    (skill_dir / test_input).parent.mkdir(parents=True, exist_ok=True)
    symlink_or_skip(str(outside), skill_dir / test_input)
    package_skill(tmp_path / "out", load(skill_dir))
    copied = (tmp_path / "out" / "plugins" / "d" / "skills" / "agree" / test_input).exists()
    assert contains(errors_of(skill_dir), "symlinks are not allowed") is expected
    assert copied is expected


def test_local_links():
    """Plain, fragment, titled and angle-bracket links are found; web and mail links are not"""
    text = '[a](x.md) [b](y.md#frag) [c](z.md "t") [d](<w.md>) [e](https://example.com "t") [f](mailto:a@b.c)'
    assert _local_links(text) == ["x.md", "y.md", "z.md", "w.md"]


@pytest.mark.parametrize(
    "test_input, expected",
    [
        ("[API](<references/api guide.md>)", ["references/api guide.md"]),
        ("[g](<a b.md#frag>)", ["a b.md"]),
        ('[g](<a b.md> "title")', ["a b.md"]),
        ("[x](#frag-only)", []),
        ("[x](<#frag-only>)", []),
        ("See [d][ref].\n\n[ref]: ../outside.md", ["../outside.md"]),
        ('[ref]: <my file.md> "Title"', ["my file.md"]),
        ("[ref]: a.md#section", ["a.md"]),
        ("   [ref]: a.md", ["a.md"]),
        ("    [ref]: a.md", []),  # four spaces is an indented code block, not a definition
        ("[ref]: https://example.com/x", []),
        ("[ref]: mailto:a@b.c", []),
        ("[one](a.md) and [ref]: not at line start", ["a.md"]),
        ("[ref](references/a(b).md)", ["references/a(b).md"]),  # balanced parentheses belong to the destination
        ("[x](a(b(c)).md)", ["a(b(c)).md"]),
        ('[x](a(b).md "Title")', ["a(b).md"]),
        ("[x](a.md) text)", ["a.md"]),  # an unbalanced closing parenthesis ends the destination
        ("[x](a\\(b.md)", ["a(b.md"]),  # a backslash escape
        ("[x](references\\guide.md)", ["references\\guide.md"]),  # a backslash before a letter is literal
        ("[x](references/api%20guide.md)", ["references/api guide.md"]),  # percent-encoding is decoded
        ("[x](<a%20b.md>)", ["a b.md"]),
        ("[x](a%23b.md#frag)", ["a#b.md"]),  # the fragment is cut before decoding, so %23 stays part of the name
        ("[x](%2e%2e/outside.md)", ["../outside.md"]),  # an encoded traversal is still a traversal
        ("[x](<unterminated.md)", []),
        ("[ref]: a(b).md", ["a(b).md"]),
        ("[ref]: references/api%20guide.md", ["references/api guide.md"]),
    ],
)
def test_local_links_forms(test_input, expected):
    """Angle-bracket destinations may contain spaces, reference definitions count, and destinations are unescaped and decoded"""
    assert _local_links(test_input) == expected


def test_check_skill_links_with_parentheses_and_percent_encoding(tmp_path):
    """Existing files whose names need escaping validate and count as linked"""
    body = "See [a](references/a(b).md), [g](references/api%20guide.md) and [d](<references/with space.md>).\n"
    files = {"references/a(b).md": "# A\n", "references/api guide.md": "# G\n", "references/with space.md": "# S\n"}
    skill = make_skill(tmp_path, "escaped", body=body, files=files)
    errors, warnings = check_skill(skill, {})
    assert errors == []
    assert warnings == []


@pytest.mark.parametrize(
    "test_input, expected",
    [
        ("%2e%2e/outside.md", "outside the skill directory"),
        ("references/missing%20file.md", "missing file 'references/missing file.md'"),
        ("references/a(b).md", "missing file 'references/a(b).md'"),
    ],
    ids=["encoded-traversal", "encoded-missing", "parentheses-missing"],
)
def test_check_skill_decoded_link_is_still_checked(test_input, expected, tmp_path):
    """Decoding the path must not let a broken or escaping link through"""
    (tmp_path / "outside.md").write_text("x", encoding="utf-8")
    skill = make_skill(tmp_path, "decoded", body=f"See [x]({test_input}).\n")
    assert contains(errors_of(skill), expected)


def test_check_skill_yaml_recursion_error(tmp_path):
    """A RecursionError from the YAML parser is a finding for that skill, and the next skill is still checked"""
    bad = make_skill(tmp_path, "nested")
    good = make_skill(tmp_path, "good-after-nesting")
    seen: dict = {}
    with patch(target="yaml.safe_load", side_effect=RecursionError("maximum recursion depth exceeded")):
        bad_errors = check_skill(bad, seen)[0]
    assert contains(bad_errors, "invalid YAML")
    assert contains(bad_errors, "RecursionError")
    assert check_skill(good, seen)[0] == []


def test_check_skill_deeply_nested_evals(tmp_path):
    """A RecursionError from the JSON parser is a finding for that skill, and the next skill is still checked"""
    bad = make_skill(tmp_path, "nested-evals", evals=None)
    (bad / "evals").mkdir()
    (bad / "evals" / "evals.json").write_text(DEEPLY_NESTED_JSON, encoding="utf-8")
    good = make_skill(tmp_path, "good-after-evals")
    seen: dict = {}
    errors = check_skill(bad, seen)[0]
    assert contains(errors, "evals/evals.json is invalid")
    assert contains(errors, "maximum recursion depth")  # a RecursionError, not "extra data" or another JSON error
    assert check_skill(good, seen)[0] == []


@pytest.mark.parametrize("fixture_dir", ["evals", "__pycache__", "deeper/evals"])
def test_check_skill_ignores_reference_fixtures_that_are_not_packaged(fixture_dir, tmp_path):
    """Markdown under an excluded directory is never shipped, so a broken link, bad bytes or a long file there is no finding"""
    outside = tmp_path / "outside.md"
    outside.write_text("x", encoding="utf-8")
    skill = make_skill(
        tmp_path / "skills",
        "fixtures",
        body="See [a](references/a.md).\n",
        files={
            "references/a.md": "# A\n",
            f"references/{fixture_dir}/bad-bytes.md": b"\xff\xfe invalid utf-8",
            f"references/{fixture_dir}/broken-link.md": "See [x](missing.md) and [y](../../../../outside.md).\n",
            f"references/{fixture_dir}/long.md": "line\n" * 150,
        },
    )
    symlink_or_skip(str(outside), skill / "references" / fixture_dir / "linked.md")
    assert check_skill(skill, {}) == ([], [])


def test_check_skill_still_reads_reference_files_outside_the_excluded_directories(tmp_path):
    """The same fixtures in a normal subdirectory are findings, so the exemption above is not just a disabled check"""
    skill = make_skill(
        tmp_path,
        "shipped",
        body="See [a](references/a.md).\n",
        files={
            "references/a.md": "# A\n",
            "references/other/bad-bytes.md": b"\xff\xfe invalid utf-8",
            "references/other/long.md": "line\n" * 150,
        },
    )
    errors = errors_of(skill)
    assert contains(errors, "cannot read reference")
    assert contains(errors, "needs a '## Contents' section")


def test_check_skill_angle_bracket_link_with_spaces(tmp_path):
    """An existing reference whose name contains a space validates, and counts as linked"""
    skill = make_skill(tmp_path, "spaced", body="See [API](<references/api guide.md>).\n", files={"references/api guide.md": "# API\n"})
    errors, warnings = check_skill(skill, {})
    assert errors == []
    assert warnings == []


def test_check_skill_reference_style_link_to_existing_file(tmp_path):
    """A reference-style link to a bundled file validates, and counts as linked"""
    body = 'See [details][ref].\n\n[ref]: references/a.md "Details"\n'
    skill = make_skill(tmp_path, "ref-ok", body=body, files={"references/a.md": "# A\n"})
    errors, warnings = check_skill(skill, {})
    assert errors == []
    assert warnings == []


@pytest.mark.parametrize(
    "test_input, expected",
    [
        ("../outside.md", "outside the skill directory"),
        ("references/missing.md", "missing file 'references/missing.md'"),
        ("evals/evals.json", "not packaged"),
        ("<references/missing guide.md>", "missing file 'references/missing guide.md'"),
    ],
    ids=["outside", "missing", "not-packaged", "angle-missing"],
)
def test_check_skill_reference_style_link_is_checked(test_input, expected, tmp_path):
    """A reference definition is validated like an inline link, so it cannot hide a broken destination"""
    (tmp_path / "outside.md").write_text("x", encoding="utf-8")
    skill = make_skill(tmp_path, "ref-bad", body=f"See [details][ref].\n\n[ref]: {test_input}\n")
    assert contains(errors_of(skill), expected)


def test_check_links_resolution_failure(tmp_path):
    """A link that cannot be resolved is a finding, not a crash"""
    looped = make_skill(tmp_path, "resolve-fail", body="See [a](references/loop.md).\n")
    add_symlink_loops(looped)
    errors, _ = _check_links("See [a](references/loop.md).", looped.resolve(), looped.resolve(), Path("resolve-fail"))
    assert len(errors) == 1
    assert any(word in errors[0] for word in ("symlink loop", "missing file", "outside"))


def test_main_real_hub(capsys):
    """Every skill in this repository validates"""
    code = main()
    assert code == 0, capsys.readouterr().out


def test_every_validated_link_exists_in_the_packaged_skill(tmp_path):
    """Links are checked against the packaged output, not just the source tree"""
    for skill_dir in discover():
        skill = load(skill_dir)
        package_skill(tmp_path / skill_dir.name, skill)
        packaged = tmp_path / skill_dir.name / "plugins" / skill.domain / "skills" / skill_dir.name
        for link in _local_links(skill.body):
            assert (packaged / link).exists(), f"{skill_dir.name}: link '{link}' missing from packaged skill"
