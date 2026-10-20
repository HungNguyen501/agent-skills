"""Shared helpers for the hub's scripts: frontmatter parsing and skill discovery."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

import yaml

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
DOMAINS_FILE = SKILLS_DIR / "domains.json"
MAX_BODY_LINES = 500
MAX_BODY_TOKENS = 5000


@dataclass
class Skill:
    domain: str
    path: Path
    meta: dict
    body: str


def load_domains(path: Path | None = None) -> dict[str, str]:
    """Read the domain registry: a JSON object that maps each domain name to a non-empty description string.

    Used by both validate.py and build.py, so a registry that validates is one the build can use.
    Raises ValueError, naming the file, for a missing file, bad JSON or the wrong shape.
    """
    path = path or DOMAINS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"{path.name} not found") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"{path.name} cannot be read as JSON: {exc.__class__.__name__}: {exc}") from exc
    valid = isinstance(data, dict) and all(isinstance(k, str) and k and isinstance(v, str) and v.strip() for k, v in data.items())
    if not valid:
        raise ValueError(f"{path.name} must be a JSON object that maps each domain name to a non-empty description string")
    return data


def estimate_tokens(text: str) -> int:
    """Rough token estimate (about 4 characters per token); good enough for a size gate."""
    return len(text) // 4


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split text into (frontmatter, body) at standalone `---` lines.

    A `---` inside a value (for example `description: a --- b`) is not a delimiter.
    Keep this identical to `_split_frontmatter` in runtimes/python/loader.py, which is copied
    into consumers and so cannot import this module.
    """
    lines = text.split("\n")
    if lines[0].rstrip() != "---":
        raise ValueError("missing YAML frontmatter")
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
    raise ValueError("unterminated YAML frontmatter")


def parse_skill_md(text: str) -> tuple[dict, str]:
    """Split a SKILL.md into (frontmatter dict, body). Raises ValueError on malformed frontmatter."""
    front, body = split_frontmatter(text)
    try:
        meta = yaml.safe_load(front)
    except (yaml.YAMLError, RecursionError) as exc:  # RecursionError: deeply nested YAML
        raise ValueError(f"invalid YAML frontmatter: {exc.__class__.__name__}: {exc}") from exc
    if not isinstance(meta, dict):
        raise ValueError("frontmatter is not a mapping")
    return meta, body.lstrip("\n")


def discover(skills_dir: Path = SKILLS_DIR) -> list[Path]:
    """Return every skill directory, laid out as <skills_dir>/<domain>/<skill>/SKILL.md."""
    return sorted(p.parent for p in skills_dir.glob("*/*/SKILL.md"))


def load(skill_dir: Path) -> Skill:
    meta, body = parse_skill_md((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    return Skill(domain=skill_dir.parent.name, path=skill_dir, meta=meta, body=body)
