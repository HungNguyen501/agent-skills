"""Reference loader for custom agent runtimes (OpenAI function calling or any chat API).

Reads skills laid out as <skills_dir>/<name>/SKILL.md, which is how each hub domain directory
(skills/<domain>/) is laid out. Requires PyYAML. Copy this file into the consumer, or import it from the hub checkout.

Loading modes:
  router: build_menu() feeds a small model that returns skill names; system_prompt() then
          injects those bodies plus every always-on skill.
  tool:   put build_menu() in the system prompt and expose TOOL_SCHEMAS. The model calls
          load_skill / read_skill_file. Dispatch with handle_tool_call().
  eager:  system_prompt(select=all names).

Skills are ordered by metadata.order (default 1000), then by name. The result of discover()
is a dict in that order, and system_prompt() keeps it.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    always: bool
    order: int
    body: str
    path: Path


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split at standalone `---` lines; a `---` inside a value is not a delimiter.

    Keep this identical to `split_frontmatter` in scripts/skilllib.py. This file is copied into
    consumers, so it cannot import that module.
    """
    lines = text.split("\n")
    if lines[0].rstrip() != "---":
        raise ValueError("missing frontmatter")
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
    raise ValueError("unterminated frontmatter")


def _parse(text: str) -> tuple[dict, str]:
    front, body = _split_frontmatter(text)
    try:
        meta = yaml.safe_load(front) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise ValueError("frontmatter is not a mapping")
    return meta, body.strip()


def _parse_order(value: object) -> int:
    """metadata.order as an int. Accepts an int or an integer string; anything else raises ValueError."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"metadata.order must be an integer, got {value!r}")
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"metadata.order must be an integer, got {value!r}") from None


def _load_skill(md: Path) -> Skill:
    """Parse one SKILL.md into a Skill. Any malformed input raises ValueError that names the file."""
    try:
        meta, body = _parse(md.read_text(encoding="utf-8"))
        name = meta.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"name must be a non-empty string, got {name!r}")
        raw_meta = meta.get("metadata")
        if raw_meta is not None and not isinstance(raw_meta, dict):  # absent or null means no metadata; anything else is a mistake
            raise ValueError(f"metadata must be a mapping, got {type(raw_meta).__name__}")
        md_meta = raw_meta or {}
        always = str(md_meta.get("always", "false")).lower() == "true"
        order = _parse_order(md_meta.get("order", 1000))
    except (TypeError, ValueError, OSError) as exc:  # parsing one file's metadata; never lose the file name
        raise ValueError(f"{md}: {exc}") from exc
    return Skill(name, str(meta.get("description", "")), always, order, body, md.parent)


def discover(
    skills_dirs: str | Path | Iterable[str | Path],
    allow: set[str] | frozenset[str] | list[str] | None = None,
) -> dict[str, Skill]:
    """Load skills from one or more directories.

    `allow` restricts routed skills to a per-consumer allowlist; always-on skills are never filtered.
    A name that appears in two places raises ValueError whether or not the allowlist would keep it,
    so a local skill can never silently shadow a hub skill. Malformed skills raise ValueError naming the file.
    """
    dirs = [skills_dirs] if isinstance(skills_dirs, (str, Path)) else list(skills_dirs)
    seen: dict[str, Path] = {}
    found: dict[str, Skill] = {}
    for skills_dir in dirs:
        for md in sorted(Path(skills_dir).glob("*/SKILL.md")):
            skill = _load_skill(md)
            if skill.name in seen:
                raise ValueError(f"duplicate skill name '{skill.name}': {seen[skill.name]} and {md.parent}")
            seen[skill.name] = md.parent
            if allow is not None and skill.name not in allow and not skill.always:
                continue
            found[skill.name] = skill
    return dict(sorted(found.items(), key=lambda kv: (kv[1].order, kv[0])))


def build_menu(skills: dict[str, Skill], include_always: bool = False) -> str:
    """One line per skill: `- name: description`. Always-on skills are omitted by default."""
    return "\n".join(
        f'- "{s.name}": {s.description}' for s in skills.values() if include_always or not s.always
    )


def system_prompt(skills: dict[str, Skill], select: set[str]) -> str:
    """Concatenate always-on skill bodies and the selected skill bodies, in load order."""
    active = [s for s in skills.values() if s.always or s.name in select]
    return "\n\n---\n\n".join(s.body for s in active)


def load_skill(skills: dict[str, Skill], name: str) -> str:
    skill = skills.get(name)
    if skill is None:
        return f"Unknown skill '{name}'. Available: {', '.join(sorted(skills))}"
    return skill.body


def read_skill_file(skills: dict[str, Skill], name: str, path: str) -> str:
    """Read a bundled file (for example references/x.md). Rejects paths outside the skill directory."""
    skill = skills.get(name)
    if skill is None:
        return f"Unknown skill '{name}'."
    try:
        root = skill.path.resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return f"File '{path}' not found in skill '{name}'."
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"File '{path}' in skill '{name}' is not UTF-8 text and cannot be read."
    except (OSError, ValueError, RuntimeError) as exc:  # RuntimeError: symlink loop on Python 3.11/3.12
        return f"File '{path}' in skill '{name}' could not be read: {exc.__class__.__name__}."


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "Load the full instructions of a skill listed in the skill menu.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_skill_file",
            "description": "Read a file bundled with a skill, such as references/x.md, when its instructions say to.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "path": {"type": "string"}},
                "required": ["name", "path"],
            },
        },
    },
]


def handle_tool_call(skills: dict[str, Skill], tool: str, args: dict) -> str | None:
    """Return the tool result, or None if `tool` is not a skill tool.

    Arguments come from a model, so they are validated here: a bad call returns an error string
    the model can act on and never raises.
    """
    required = {"load_skill": ("name",), "read_skill_file": ("name", "path")}.get(tool)
    if required is None:
        return None
    if not isinstance(args, dict):
        return f"Invalid arguments for {tool}: expected a JSON object with string fields {', '.join(required)}."
    for key in required:
        value = args.get(key)
        if not isinstance(value, str) or not value:
            return f"Invalid argument '{key}' for {tool}: expected a non-empty string, got {type(value).__name__}."
    if tool == "load_skill":
        return load_skill(skills, args["name"])
    return read_skill_file(skills, args["name"], args["path"])
