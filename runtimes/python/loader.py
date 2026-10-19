"""Reference loader for custom agent runtimes (OpenAI function calling or any chat API).

Reads skills laid out as <skills_dir>/<name>/SKILL.md, as written by scripts/sync.py.
Requires PyYAML. Copy this file into the consumer, or import it from the hub checkout.

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


def _parse(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter")
    _, front, body = text.split("---\n", 2)
    return yaml.safe_load(front) or {}, body.strip()


def discover(
    skills_dirs: str | Path | Iterable[str | Path],
    allow: set[str] | frozenset[str] | list[str] | None = None,
) -> dict[str, Skill]:
    """Load skills from one or more directories.

    `allow` restricts routed skills to a per-consumer allowlist; always-on skills are never filtered.
    A name that appears in two directories raises ValueError, so a local skill cannot silently shadow a hub skill.
    """
    dirs = [skills_dirs] if isinstance(skills_dirs, (str, Path)) else list(skills_dirs)
    found: dict[str, Skill] = {}
    for skills_dir in dirs:
        for md in sorted(Path(skills_dir).glob("*/SKILL.md")):
            meta, body = _parse(md.read_text(encoding="utf-8"))
            name = meta["name"]
            if name in found:
                raise ValueError(f"duplicate skill name '{name}': {found[name].path} and {md.parent}")
            md_meta = meta.get("metadata") or {}
            always = str(md_meta.get("always", "false")).lower() == "true"
            if allow is not None and name not in allow and not always:
                continue
            found[name] = Skill(
                name, meta.get("description", ""), always, int(md_meta.get("order", 1000)), body, md.parent
            )
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
    root = skill.path.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return f"File '{path}' not found in skill '{name}'."
    return target.read_text(encoding="utf-8")


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
    """Return the tool result, or None if `tool` is not a skill tool."""
    if tool == "load_skill":
        return load_skill(skills, args.get("name", ""))
    if tool == "read_skill_file":
        return read_skill_file(skills, args.get("name", ""), args.get("path", ""))
    return None
