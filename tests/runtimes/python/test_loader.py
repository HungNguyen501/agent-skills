"""Unit tests for module loader"""
from unittest.mock import patch

import pytest

from loader import _parse, _split_frontmatter, discover, handle_tool_call, read_skill_file
from tests.mocks import DEEPLY_NESTED, add_symlink_loops, fm, make_skill
from validate import check_skill

ALWAYS_ON = 'metadata:\n  always: "true"\n'
BAD_VALUES = [None, ["a"], {"a": 1}, 5, True, ""]


@pytest.fixture(name="demo")
def gen_demo_skills(tmp_path):
    """A loaded `demo` skill with a text reference and a binary asset, next to a secret that is outside the skill"""
    make_skill(tmp_path, "demo", files={"references/ok.md": "hello", "assets/blob.bin": b"\xff\xfe\x00\x80"})
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    return tmp_path, discover(tmp_path)


def test_parse_triple_dash_inside_a_value():
    """A --- inside a frontmatter value or the body is not a delimiter"""
    front = 'name: demo\ndescription: Use when comparing ---\nmetadata:\n  always: "true"\n'
    meta, body = _parse(f"---\n{front}---\nBODY\n---\nafter rule\n")
    assert meta["description"] == "Use when comparing ---"
    assert "after rule" in body


def test_split_frontmatter_only_a_standalone_delimiter_line_ends_it():
    """A line that merely starts with --- is part of the frontmatter, and trailing whitespace on the delimiter is allowed"""
    front, body = _split_frontmatter("---\nname: x\n--- not the end\nmore\n---  \nbody\n")
    assert front == "name: x\n--- not the end\nmore"
    assert body == "body\n"


@pytest.mark.parametrize(
    "test_input",
    [
        "no frontmatter\n",
        "---\nname: x\nnever closed\n",
        "---\n- a\n- b\n---\nbody\n",
        "---\nname: [\n---\nbody\n",
    ],
    ids=["no-frontmatter", "unterminated", "not-a-mapping", "invalid-yaml"],
)
def test_parse_malformed(test_input):
    """Malformed frontmatter raises ValueError"""
    with pytest.raises(ValueError):
        _parse(test_input)


def test_parse_deeply_nested_yaml():
    """The parser's RecursionError becomes a ValueError"""
    with pytest.raises(ValueError, match="invalid YAML frontmatter"):
        _parse(f"---\nname: x\nmeta: {DEEPLY_NESTED}\n---\nbody\n")


@patch(target="yaml.safe_load", side_effect=RecursionError("maximum recursion depth exceeded"))
def test_discover_yaml_recursion_error_names_the_file(mock_load, tmp_path):
    """A skill the parser cannot handle is reported by name, as a ValueError"""
    make_skill(tmp_path, "nested")
    with pytest.raises(ValueError, match="nested.*invalid YAML frontmatter.*RecursionError"):
        discover(tmp_path)
    assert mock_load.called


def test_discover_duplicate_name_across_directories(tmp_path):
    """A local skill can never silently shadow another one"""
    make_skill(tmp_path / "a", "dup")
    make_skill(tmp_path / "b", "dup")
    with pytest.raises(ValueError, match="duplicate skill name 'dup'"):
        discover([tmp_path / "a", tmp_path / "b"])


def test_discover_duplicate_name_that_the_allowlist_excludes(tmp_path):
    """Duplicates are detected before the allowlist is applied"""
    make_skill(tmp_path / "a", "dup")
    make_skill(tmp_path / "b", "dup")
    make_skill(tmp_path / "a", "wanted")
    with pytest.raises(ValueError, match="duplicate skill name"):
        discover([tmp_path / "a", tmp_path / "b"], allow={"wanted"})


def test_discover_allowlist_filters_routed_skills_but_not_always_on(tmp_path):
    """Always-on skills are never filtered by the allowlist"""
    make_skill(tmp_path, "routed-a")
    make_skill(tmp_path, "routed-b")
    make_skill(tmp_path, "core", frontmatter=fm("core", ALWAYS_ON))
    assert sorted(discover(tmp_path, allow={"routed-a"})) == ["core", "routed-a"]


def test_discover_sorts_by_order_then_name(tmp_path):
    """Happy path"""
    for name, order in (("late", "30"), ("early", "5"), ("middle", "10")):
        make_skill(tmp_path, name, frontmatter=fm(name, f'metadata:\n  order: "{order}"\n'))
    assert list(discover(tmp_path)) == ["early", "middle", "late"]


def test_discover_integer_and_integer_string_order(tmp_path):
    """An unquoted integer is accepted as well as a quoted one"""
    make_skill(tmp_path, "int-order", frontmatter=fm("int-order", "metadata:\n  order: 7\n"))
    make_skill(tmp_path, "str-order", frontmatter=fm("str-order", 'metadata:\n  order: "3"\n'))
    assert list(discover(tmp_path)) == ["str-order", "int-order"]


@pytest.mark.parametrize(
    "test_input",
    ["null", "[1, 2]", "true", "1.5", "abc", '"1.5"'],
    ids=["null", "list", "bool", "float", "text", "float-string"],
)
def test_discover_malformed_order(test_input, tmp_path):
    """A ValueError that names the file, never a bare TypeError"""
    make_skill(tmp_path, "bad-order", frontmatter=fm("bad-order", f"metadata:\n  order: {test_input}\n"))
    with pytest.raises(ValueError, match="bad-order.*metadata.order"):
        discover(tmp_path)


@pytest.mark.parametrize("test_input", ["always", "[always, order]", "5", "true"])
def test_discover_non_mapping_metadata(test_input, tmp_path):
    """Dropping the block would silently turn an always-on skill into a routed one, so it raises"""
    make_skill(tmp_path, "meta-skill", frontmatter=fm("meta-skill", f"metadata: {test_input}\n"))
    with pytest.raises(ValueError, match="meta-skill.*metadata must be a mapping"):
        discover(tmp_path)


@pytest.mark.parametrize("test_input", ["always", "[always, order]", "5", "true"])
def test_discover_rejects_the_same_metadata_as_the_validator(test_input, tmp_path):
    """A skill must not pass validation and then fail to load at runtime"""
    skill = make_skill(tmp_path, "same-rule", frontmatter=fm("same-rule", f"metadata: {test_input}\n"))
    assert any("metadata must be a mapping" in e for e in check_skill(skill, {})[0])
    with pytest.raises(ValueError):
        discover(tmp_path)


def test_discover_absent_null_and_empty_metadata(tmp_path):
    """Happy path - no metadata means no always-on and the default order"""
    make_skill(tmp_path, "no-meta")
    make_skill(tmp_path, "null-meta", frontmatter=fm("null-meta", "metadata:\n"))
    make_skill(tmp_path, "empty-meta", frontmatter=fm("empty-meta", "metadata: {}\n"))
    found = discover(tmp_path)
    assert sorted(found) == ["empty-meta", "no-meta", "null-meta"]
    assert not any(s.always for s in found.values())


def test_discover_malformed_skill_names_the_file(tmp_path):
    """The error says which skill is broken"""
    make_skill(tmp_path, "broken", frontmatter="name: broken\ndescription: [\n")
    with pytest.raises(ValueError, match="broken"):
        discover(tmp_path)


def test_read_skill_file(demo):
    """Text is returned. A binary file, traversal, a directory and a missing file give an error message"""
    _, skills = demo
    assert read_skill_file(skills, "demo", "references/ok.md") == "hello"
    assert "not UTF-8" in read_skill_file(skills, "demo", "assets/blob.bin")
    for path in ("../secret.txt", "references", "nope.md"):
        assert "not found" in read_skill_file(skills, "demo", path), path


def test_read_skill_file_symlink_loop(demo):
    """A loop returns an error string from both entry points and never raises RuntimeError"""
    tmp_path, skills = demo
    add_symlink_loops(tmp_path / "demo")
    for path in ("references/loop.md", "references/a.md", "references/b.md"):
        direct = read_skill_file(skills, "demo", path)
        via_tool = handle_tool_call(skills, "read_skill_file", {"name": "demo", "path": path})
        for result in (direct, via_tool):
            assert isinstance(result, str)
            assert "could not be read" in result or "not found" in result


def test_read_skill_file_nul_byte_in_path(demo):
    """Returns an error string"""
    _, skills = demo
    assert isinstance(handle_tool_call(skills, "read_skill_file", {"name": "demo", "path": "a\x00b"}), str)


@pytest.mark.parametrize("tool, extra", [("load_skill", {}), ("read_skill_file", {"path": "references/ok.md"})])
@pytest.mark.parametrize("bad_name", BAD_VALUES, ids=repr)
def test_handle_tool_call_invalid_name(tool, extra, bad_name, demo):
    """A bad name from the model returns an error string for either tool"""
    _, skills = demo
    assert "Invalid argument 'name'" in handle_tool_call(skills, tool, {"name": bad_name, **extra})


@pytest.mark.parametrize("bad_path", BAD_VALUES, ids=repr)
def test_handle_tool_call_invalid_path(bad_path, demo):
    """A bad path from the model returns an error string"""
    _, skills = demo
    assert "Invalid argument 'path'" in handle_tool_call(skills, "read_skill_file", {"name": "demo", "path": bad_path})


def test_handle_tool_call_missing_arguments(demo):
    """Missing arguments return an error string"""
    _, skills = demo
    assert "Invalid argument 'name'" in handle_tool_call(skills, "load_skill", {})
    assert "Invalid argument 'path'" in handle_tool_call(skills, "read_skill_file", {"name": "demo"})


@pytest.mark.parametrize("tool", ["load_skill", "read_skill_file"])
@pytest.mark.parametrize("bad_args", [None, ["demo"], "demo", 5], ids=repr)
def test_handle_tool_call_non_object_arguments(tool, bad_args, demo):
    """Arguments that are not a JSON object return an error string"""
    _, skills = demo
    assert "Invalid arguments" in handle_tool_call(skills, tool, bad_args)


def test_handle_tool_call(demo):
    """Valid calls return the content, an unknown skill returns a message, and a tool that is not ours returns None"""
    _, skills = demo
    assert handle_tool_call(skills, "load_skill", {"name": "demo"}) == "Body."
    assert handle_tool_call(skills, "read_skill_file", {"name": "demo", "path": "references/ok.md"}) == "hello"
    assert "Unknown skill" in handle_tool_call(skills, "load_skill", {"name": "nope"})
    assert handle_tool_call(skills, "execute_query", {"sql": "select 1"}) is None
