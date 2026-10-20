"""Unit tests for module skilllib"""
import pytest

from skilllib import discover, estimate_tokens, load, load_domains, parse_skill_md, split_frontmatter
from tests.mocks import DEEPLY_NESTED, fm, make_skill

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


def test_parse_skill_md_deeply_nested_yaml():
    """The parser's RecursionError becomes a ValueError, so callers that handle bad input see it"""
    with pytest.raises(ValueError, match="invalid YAML frontmatter"):
        parse_skill_md(f"---\nname: x\nmeta: {DEEPLY_NESTED}\n---\nbody\n")


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


def test_load_domains(tmp_path):
    """Happy path - a mapping of domain names to descriptions"""
    registry = tmp_path / "domains.json"
    registry.write_text('{"authoring": "Guidance.", "databricks": "Data."}', encoding="utf-8")
    assert load_domains(registry) == {"authoring": "Guidance.", "databricks": "Data."}


def test_load_domains_real_registry():
    """The registry in this repository is well formed, and every domain directory is registered"""
    domains = load_domains()
    assert domains
    assert {d.parent.name for d in discover()} <= set(domains)


@pytest.mark.parametrize(
    "test_input",
    [
        '["authoring", "databricks"]',
        '"authoring"',
        "null",
        '{"authoring": 1}',
        '{"authoring": null}',
        '{"authoring": ["x"]}',
        '{"authoring": ""}',
        '{"authoring": "   "}',
        '{"": "no name"}',
        "{not json",
        "",
        "[" * 100_000 + "]" * 100_000,
    ],
    ids=[
        "list", "string", "null", "int-value", "null-value", "list-value",
        "empty-description", "blank-description", "empty-name", "bad-json", "empty-file", "too-deep",
    ],
)
def test_load_domains_malformed(test_input, tmp_path):
    """Anything but a mapping of names to non-empty strings is a ValueError that names the file"""
    registry = tmp_path / "domains.json"
    registry.write_text(test_input, encoding="utf-8")
    with pytest.raises(ValueError, match="domains.json"):
        load_domains(registry)


def test_load_domains_missing_file(tmp_path):
    """A missing registry is a ValueError, not a FileNotFoundError traceback"""
    with pytest.raises(ValueError, match="domains.json not found"):
        load_domains(tmp_path / "domains.json")


@pytest.mark.parametrize("test_input, expected", [("x" * 400, 100), ("", 0), ("abc", 0)])
def test_estimate_tokens(test_input, expected):
    """Roughly four characters per token"""
    assert estimate_tokens(test_input) == expected
