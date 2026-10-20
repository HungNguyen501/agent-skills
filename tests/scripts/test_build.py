"""Unit tests for module build"""
from unittest.mock import patch
import shutil
import sys

import pytest

from build import OUTPUTS, _same, ensure_packageable, generate, install_outputs, main, package_skill
from skilllib import load
from tests.mocks import REPO_ROOT, add_symlink_loops, make_skill, symlink_or_skip


@patch(target="skilllib.discover", return_value=[])
def test_generate_without_skills(mock_discover, tmp_path):
    """An empty skill collection still produces every output directory, and two builds compare equal"""
    first, second = tmp_path / "one", tmp_path / "two"
    generate(first)
    generate(second)
    assert mock_discover.called
    for name in OUTPUTS:
        assert (first / name).exists(), name
        assert _same(first / name, second / name), name


def unsafe_skill_dirs(tmp_path):
    """Skills that a copy would follow a link out of: a linked skill root, a linked domain root and links in packaged paths"""
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    real = make_skill(tmp_path / "real", "real-skill")
    skills = tmp_path / "skills"
    (skills / "d").mkdir(parents=True)
    linked_skill = skills / "d" / "linked-skill"
    symlink_or_skip(str(real), linked_skill)
    real_domain = tmp_path / "real-domain"
    make_skill(real_domain, "in-linked-domain")
    symlink_or_skip(str(real_domain), skills / "linked-domain")
    file_link = make_skill(skills / "d", "file-link")
    symlink_or_skip(str(outside), file_link / "references-leak.md")
    dir_link = make_skill(skills / "d", "dir-link")
    symlink_or_skip(str(tmp_path), dir_link / "escape")
    loop = make_skill(skills / "d", "loop")
    add_symlink_loops(loop)
    return {
        "linked-skill-root": linked_skill,
        "linked-domain-root": skills / "linked-domain" / "in-linked-domain",
        "file-link": file_link,
        "directory-link": dir_link,
        "link-loop": loop,
    }


@pytest.mark.parametrize("kind", ["linked-skill-root", "linked-domain-root", "file-link", "directory-link", "link-loop"])
def test_generate_refuses_a_skill_that_a_copy_would_follow_a_link_out_of(kind, tmp_path):
    """Nothing is read through the link and nothing is written, so no outside file can reach the distributable output"""
    skill_dir = unsafe_skill_dirs(tmp_path)[kind]
    out = tmp_path / "out"
    out.mkdir()
    domains = {skill_dir.parent.name: "Test domain."}
    with (
        patch(target="skilllib.discover", return_value=[skill_dir]),
        patch(target="skilllib.load_domains", return_value=domains),
        pytest.raises(ValueError, match="refusing to package"),
    ):
        generate(out)
    assert list(out.iterdir()) == []


@pytest.mark.parametrize("kind", ["file-link", "directory-link", "link-loop"])
def test_package_skill_refuses_links_even_when_called_directly(kind, tmp_path):
    """The guard is in package_skill itself, so it holds for every caller and not only for generate()"""
    skill_dir = unsafe_skill_dirs(tmp_path)[kind]
    with pytest.raises(ValueError, match="is a symlink"):
        package_skill(tmp_path / "out", load(skill_dir))
    assert not (tmp_path / "out").exists()


def test_ensure_packageable_ignores_links_in_excluded_paths(tmp_path):
    """evals/ and __pycache__/ are never copied, so a link there is not a reason to refuse"""
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    skill = make_skill(tmp_path / "skills" / "d", "fine", files={"__pycache__/keep.txt": "x"})
    symlink_or_skip(str(outside), skill / "evals" / "link.json")
    symlink_or_skip(str(outside), skill / "__pycache__" / "x.pyc")
    assert ensure_packageable(skill) is None


@patch(target="skilllib.load_domains", return_value={"d": "Test domain."})
def test_main_reports_an_unsafe_skill_and_installs_nothing(mock_domains, tmp_path, capsys):
    """The build exits with an error message instead of a traceback, and does not touch the committed outputs"""
    skill_dir = unsafe_skill_dirs(tmp_path)["file-link"]
    with patch.object(sys, "argv", ["build.py", "--check"]), patch(target="skilllib.discover", return_value=[skill_dir]):
        code = main()
    assert code == 1
    assert "error: refusing to package file-link" in capsys.readouterr().out
    assert mock_domains.called


def test_generate_skill_in_an_unregistered_domain(tmp_path):
    """A clear error, not a KeyError traceback"""
    skill = make_skill(tmp_path / "skills" / "unlisted", "some-skill")
    with (
        patch(target="skilllib.discover", return_value=[skill]),
        patch(target="skilllib.load_domains", return_value={"other": "x"}),
        pytest.raises(ValueError, match="domain.*missing from skills/domains.json: unlisted"),
    ):
        generate(tmp_path / "out")


@pytest.mark.parametrize("test_input", ['["authoring"]', '{"authoring": 5}', "{not json"], ids=["list", "non-string", "bad-json"])
def test_generate_malformed_domain_registry(test_input, tmp_path):
    """The build rejects the same registries the validator rejects, so a registry that validates always builds"""
    registry = tmp_path / "domains.json"
    registry.write_text(test_input, encoding="utf-8")
    with patch(target="skilllib.DOMAINS_FILE", new=registry), pytest.raises(ValueError, match="domains.json"):
        generate(tmp_path / "out")


def test_generate_matches_the_committed_outputs(tmp_path):
    """The committed plugins/ and .claude-plugin/ are up to date; run scripts/build.py when this fails"""
    generate(tmp_path)
    for name in OUTPUTS:
        assert _same(tmp_path / name, REPO_ROOT / name), f"{name} is stale; run scripts/build.py"


@pytest.fixture(name="fresh_outputs")
def gen_fresh_outputs(tmp_path):
    """A freshly generated tree with one file in each output, in its own directory"""
    fresh = tmp_path / "fresh"
    for name in OUTPUTS:
        (fresh / name).mkdir(parents=True)
        (fresh / name / "new.txt").write_text("new", encoding="utf-8")
    return fresh


@pytest.mark.parametrize("kind", ["live-directory-link", "dangling-link", "file-link", "directory", "file", "missing"])
def test_install_outputs(kind, fresh_outputs, tmp_path):
    """Every state an output root can be in is replaced, and a link is removed as a link"""
    root, precious = tmp_path / "root", tmp_path / "precious"
    root.mkdir()
    precious.mkdir()
    (precious / "keep.txt").write_text("keep", encoding="utf-8")
    (tmp_path / "a-file.txt").write_text("x", encoding="utf-8")
    for name in OUTPUTS:
        target = root / name
        if kind == "live-directory-link":
            symlink_or_skip(str(precious), target)
        elif kind == "dangling-link":
            symlink_or_skip(str(tmp_path / "does-not-exist"), target)
        elif kind == "file-link":
            symlink_or_skip(str(tmp_path / "a-file.txt"), target)
        elif kind == "directory":
            target.mkdir()
            (target / "old.txt").write_text("old", encoding="utf-8")
        elif kind == "file":
            target.write_text("old", encoding="utf-8")
    install_outputs(fresh_outputs, root)
    for name in OUTPUTS:
        assert not (root / name).is_symlink(), name
        assert (root / name / "new.txt").read_text(encoding="utf-8") == "new", name
        assert not (root / name / "old.txt").exists(), name
    assert (precious / "keep.txt").read_text(encoding="utf-8") == "keep"  # the link's target is never touched
    assert (tmp_path / "a-file.txt").is_file()


def test_same_reports_a_symlinked_output_root_so_that_a_rebuild_is_recommended_and_works(fresh_outputs, tmp_path):
    """--check flags a link at an output root, and installing repairs it, which is what the message tells you to do"""
    root, elsewhere = tmp_path / "root", tmp_path / "elsewhere"
    root.mkdir()
    elsewhere.mkdir()
    for name in OUTPUTS:
        (elsewhere / name).mkdir()
        (elsewhere / name / "new.txt").write_text("new", encoding="utf-8")  # identical content behind the link
        symlink_or_skip(str(elsewhere / name), root / name)
        assert not _same(fresh_outputs / name, root / name), name
    install_outputs(fresh_outputs, root)
    for name in OUTPUTS:
        assert not (root / name).is_symlink(), name
        assert (root / name / "new.txt").is_file(), name


@pytest.mark.parametrize("test_input", ["tags", ".git", "CVS"])
def test_same_compares_names_that_dircmp_ignores_by_default(test_input, tmp_path):
    """filecmp.dircmp skips these names unless ignore=[], but packaging copies them, so --check has to compare them"""
    a, b = tmp_path / "a", tmp_path / "b"
    for directory in (a, b):
        directory.mkdir()
        (directory / "SKILL.md").write_text("same", encoding="utf-8")
    (a / test_input).write_text("one", encoding="utf-8")
    (b / test_input).write_text("two", encoding="utf-8")
    assert not _same(a, b), "changed"
    (b / test_input).unlink()
    assert not _same(a, b), "missing"
    (b / test_input).write_text("one", encoding="utf-8")
    assert _same(a, b), "identical"


def test_same_executable_bit_only_difference(tmp_path):
    """Equal content with a different owner executable bit is not the same file"""
    a, b = tmp_path / "a.sh", tmp_path / "b.sh"
    for path in (a, b):
        path.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        path.chmod(0o644)
    assert _same(a, b)
    a.chmod(0o755)
    assert not _same(a, b)
    b.chmod(0o755)
    assert _same(a, b)


@pytest.mark.parametrize(
    "test_input",
    [(0o755, 0o700), (0o645, 0o604)],
    ids=["same-owner-exec", "no-owner-exec"],
)
def test_same_ignores_group_and_other_permission_bits(test_input, tmp_path):
    """Git tracks only the owner executable bit, so other differences must not make --check fail forever"""
    a, b = tmp_path / "a.sh", tmp_path / "b.sh"
    for path in (a, b):
        path.write_text("echo hi\n", encoding="utf-8")
    a.chmod(test_input[0])
    b.chmod(test_input[1])
    assert _same(a, b)


@pytest.mark.parametrize("link_on_left", [False, True], ids=["link-in-committed", "link-in-generated"])
def test_same_file_replaced_by_a_symlink(link_on_left, tmp_path):
    """A link to identical content must not pass, in either argument position"""
    real, plain, link = tmp_path / "real.md", tmp_path / "plain.md", tmp_path / "link.md"
    real.write_text("same", encoding="utf-8")
    plain.write_text("same", encoding="utf-8")
    symlink_or_skip(str(real), link)
    a, b = (link, plain) if link_on_left else (plain, link)
    assert not _same(a, b)


@pytest.mark.parametrize("link_on_left", [False, True], ids=["link-in-committed", "link-in-generated"])
def test_same_directory_replaced_by_a_symlink(link_on_left, tmp_path):
    """A link to a directory with identical content must not pass, in either argument position"""
    real, plain, link = tmp_path / "real", tmp_path / "plain", tmp_path / "link"
    for directory in (real, plain):
        directory.mkdir()
        (directory / "SKILL.md").write_text("same", encoding="utf-8")
    symlink_or_skip(str(real), link)
    a, b = (link, plain) if link_on_left else (plain, link)
    assert not _same(a, b)


def test_same_symlink_nested_in_a_compared_tree(tmp_path):
    """A file or a directory swapped for a link deep inside the tree is found, and a broken link is a difference too"""
    trees = {}
    for label in ("a", "b"):
        root = tmp_path / label
        (root / "refs" / "sub").mkdir(parents=True)
        (root / "refs" / "note.md").write_text("same", encoding="utf-8")
        (root / "refs" / "sub" / "deep.md").write_text("same", encoding="utf-8")
        trees[label] = root
    assert _same(trees["a"], trees["b"])

    (trees["b"] / "refs" / "note.md").unlink()
    symlink_or_skip(str(trees["a"] / "refs" / "note.md"), trees["b"] / "refs" / "note.md")
    assert not _same(trees["a"], trees["b"]), "file replaced by a link"

    (trees["b"] / "refs" / "note.md").unlink()
    (trees["b"] / "refs" / "note.md").write_text("same", encoding="utf-8")
    shutil.rmtree(trees["b"] / "refs" / "sub")
    symlink_or_skip(str(trees["a"] / "refs" / "sub"), trees["b"] / "refs" / "sub")
    assert not _same(trees["a"], trees["b"]), "directory replaced by a link"

    (trees["b"] / "refs" / "sub").unlink()
    symlink_or_skip(str(tmp_path / "does-not-exist"), trees["b"] / "refs" / "sub")
    assert not _same(trees["a"], trees["b"]), "directory replaced by a broken link"


def test_same_executable_bit_in_nested_files(tmp_path):
    """The executable bit is compared for files inside compared directories too"""
    da, db = tmp_path / "da", tmp_path / "db"
    for directory in (da, db):
        (directory / "scripts").mkdir(parents=True)
        (directory / "scripts" / "run.py").write_text("print(1)\n", encoding="utf-8")
        (directory / "scripts" / "run.py").chmod(0o644)
    assert _same(da, db)
    (da / "scripts" / "run.py").chmod(0o755)
    assert not _same(da, db)
