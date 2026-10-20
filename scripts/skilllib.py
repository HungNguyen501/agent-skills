"""Shared helpers for the hub's scripts: frontmatter parsing and skill discovery."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
MAX_BODY_LINES = 500
MAX_BODY_TOKENS = 5000
# Names left out of packaged and synced skills (matched at any depth). validate.py rejects links into them.
# Keep identical to PACKAGE_IGNORE in scripts/sync.py, which stays stdlib-only so it cannot import this module.
PACKAGE_IGNORE = ("evals", "__pycache__")


@dataclass
class Skill:
    domain: str
    path: Path
    meta: dict
    body: str

    @property
    def name(self) -> str:
        return str(self.meta.get("name", ""))

    @property
    def custom(self) -> dict:
        """The metadata: mapping, or {} when it is absent or not a mapping (validate.py reports that)."""
        value = self.meta.get("metadata")
        return value if isinstance(value, dict) else {}

    @property
    def always(self) -> bool:
        return str(self.custom.get("always", "false")).lower() == "true"

    @property
    def order(self) -> int:
        """Prompt load order for consumers that concatenate skills; lower loads first."""
        return int(self.custom.get("order", 1000))


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
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise ValueError("frontmatter is not a mapping")
    return meta, body.lstrip("\n")


def discover(skills_dir: Path = SKILLS_DIR) -> list[Path]:
    """Return every skill directory, laid out as <skills_dir>/<domain>/<skill>/SKILL.md."""
    return sorted(p.parent for p in skills_dir.glob("*/*/SKILL.md"))


def load(skill_dir: Path) -> Skill:
    meta, body = parse_skill_md((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    return Skill(domain=skill_dir.parent.name, path=skill_dir, meta=meta, body=body)
