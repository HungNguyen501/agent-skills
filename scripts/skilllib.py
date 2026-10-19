"""Shared helpers for the hub's scripts: frontmatter parsing and skill discovery."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
MAX_BODY_LINES = 500
MAX_BODY_TOKENS = 5000


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
    def always(self) -> bool:
        return str((self.meta.get("metadata") or {}).get("always", "false")).lower() == "true"


    @property
    def order(self) -> int:
        """Prompt load order for consumers that concatenate skills; lower loads first."""
        return int((self.meta.get("metadata") or {}).get("order", 1000))


def estimate_tokens(text: str) -> int:
    """Rough token estimate (about 4 characters per token); good enough for a size gate."""
    return len(text) // 4


def parse_skill_md(text: str) -> tuple[dict, str]:
    """Split a SKILL.md into (frontmatter dict, body). Raises ValueError on malformed frontmatter."""
    if not text.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")
    parts = text.split("---\n", 2)
    if len(parts) != 3:
        raise ValueError("unterminated YAML frontmatter")
    meta = yaml.safe_load(parts[1])
    if not isinstance(meta, dict):
        raise ValueError("frontmatter is not a mapping")
    return meta, parts[2].lstrip("\n")


def discover(skills_dir: Path = SKILLS_DIR) -> list[Path]:
    """Return every skill directory, laid out as <skills_dir>/<domain>/<skill>/SKILL.md."""
    return sorted(p.parent for p in skills_dir.glob("*/*/SKILL.md"))


def load(skill_dir: Path) -> Skill:
    meta, body = parse_skill_md((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    return Skill(domain=skill_dir.parent.name, path=skill_dir, meta=meta, body=body)
