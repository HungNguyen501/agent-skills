"""Unit tests for module skilllib"""
import pytest

from skilllib import discover, estimate_tokens, load, parse_skill_md, split_frontmatter
from tests.mocks import fm, make_skill

FRONT = 'name: demo\ndescription: Use when comparing ---\nmetadata:\n  always: "true"\n'


def test_parse_skill_md_triple_dash_inside_a_value():
    """A --- inside a frontmatter value or the body is not a delimiter"""
    meta, body = parse_skill_md(f"---\n{FRONT}---\nBODY\n---\nafter rule\n")
    assert meta["description"] == "Use when comparing ---"
    assert "after rule" in body


def test_split_frontmatter_only_a_standalone_delimiter_line_ends_it():
    """A line that merely starts with --- is part of the frontmatter, and trailing whitespace on the delimiter is allowed"""
    front, body = split_frontmatter("---\nname: x\n--- not the end\nmore\n---  \nbody\n")
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
def test_parse_skill_md_malformed(test_input):
    """Malformed frontmatter raises ValueError"""
    with pytest.raises(ValueError):
        parse_skill_md(test_input)


def test_parse_skill_md_strips_leading_blank_lines_from_body():
    """Happy path"""
    _, body = parse_skill_md("---\nname: x\n---\n\n\nFirst line\n")
    assert body == "First line\n"


def test_discover(tmp_path):
    """Skills are found in the <domain>/<skill>/SKILL.md layout and other directories are ignored"""
    first = make_skill(tmp_path / "domain-a", "one")
    second = make_skill(tmp_path / "domain-b", "two")
    (tmp_path / "domain-a" / "not-a-skill").mkdir()
    assert discover(tmp_path) == [first, second]


def test_load(tmp_path):
    """Happy path"""
    skill_dir = make_skill(tmp_path / "dom", "demo", frontmatter=fm("demo"), body="Hello\n")
    skill = load(skill_dir)
    assert skill.domain == "dom"
    assert skill.path == skill_dir
    assert skill.meta["name"] == "demo"
    assert skill.body == "Hello\n"


@pytest.mark.parametrize("test_input, expected", [("x" * 400, 100), ("", 0), ("abc", 0)])
def test_estimate_tokens(test_input, expected):
    """Roughly four characters per token"""
    assert estimate_tokens(test_input) == expected
