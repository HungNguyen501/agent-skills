"""Generate the two standalone scaffold scripts from scripts/templates/scaffold.py.tmpl.

Each skill folder ships on its own, so a script cannot import shared code from another skill. The hub keeps one
implementation instead and generates a copy per layout. Never edit the generated scripts by hand: build.py rewrites
them, and `build.py --check` fails when they differ from the template.
"""
from __future__ import annotations

import re
from pathlib import Path

from skilllib import ROOT

TEMPLATE = Path("scripts/templates/scaffold.py.tmpl")
HEADER = "# GENERATED from scripts/templates/scaffold.py.tmpl by scripts/build.py. Edit the template, not this file.\n"
VARIANTS = {
    "claude": {
        "path": Path("skills/scaffolding/scaffold-agent-repo-cc/scripts/scaffold.py"),
        "tokens": {
            "LAYOUT": "Claude Code",
            "SKILLS_DIR": ".claude/skills",
            "INSTRUCTIONS": "CLAUDE.md",
            "EXTRA_FILES": '(".claude/settings.example.json", ".gitignore")',
        },
    },
    "codex": {
        "path": Path("skills/scaffolding/scaffold-agent-repo-codex/scripts/scaffold.py"),
        "tokens": {"LAYOUT": "Codex", "SKILLS_DIR": ".agents/skills", "INSTRUCTIONS": "AGENTS.md", "EXTRA_FILES": "()"},
    },
}
BLOCK_RE = re.compile(r"^[ \t]*(?:#[ \t]*)?@@(IF[ \t]+(\w+)|END)[ \t]*$")
TOKEN_RE = re.compile(r"@@(\w+)@@")
BLANK_RUN_RE = re.compile(r"\n{4,}")  # more than two blank lines in a row, which a removed block can leave


def fill(template: str, tokens: dict[str, str], flags: set[str]) -> str:
    """Keep the `@@IF flag` ... `@@END` blocks whose flag is set, drop the others, and replace each @@TOKEN@@.

    Block markers sit on their own line, bare or behind a `#`. Blocks do not nest. Raises ValueError on an unbalanced
    block or an unknown token, because either one is a bug in the template.
    """
    kept, keep, in_block = [], True, False
    for number, line in enumerate(template.splitlines(keepends=True), 1):
        marker = BLOCK_RE.match(line)
        if not marker:
            if keep:
                kept.append(line)
        elif marker.group(1) == "END":
            if not in_block:
                raise ValueError(f"template line {number}: @@END without @@IF")
            keep, in_block = True, False
        else:
            if in_block:
                raise ValueError(f"template line {number}: blocks do not nest")
            keep, in_block = marker.group(2) in flags, True
    if in_block:
        raise ValueError("template ends inside an @@IF block")

    def sub(match: re.Match) -> str:
        if match.group(1) not in tokens:
            raise ValueError(f"unknown token @@{match.group(1)}@@ in the template")
        return tokens[match.group(1)]

    return BLANK_RUN_RE.sub("\n\n\n", TOKEN_RE.sub(sub, "".join(kept)))


def render(variant: str, root: Path = ROOT) -> str:
    """The full text of the generated script for `variant` ("claude" or "codex")."""
    spec = VARIANTS[variant]
    text = fill((root / TEMPLATE).read_text(encoding="utf-8"), spec["tokens"], {variant})
    return HEADER + text


def stale(root: Path = ROOT) -> list[Path]:
    """Generated scripts, relative to `root`, that are missing or differ from what the template produces."""
    out = []
    for variant, spec in VARIANTS.items():
        path = root / spec["path"]
        if not path.is_file() or path.read_text(encoding="utf-8") != render(variant, root):
            out.append(spec["path"])
    return out


def write_all(root: Path = ROOT) -> list[Path]:
    """Write every script that is missing or differs. Returns the ones written, relative to `root`."""
    written = []
    for variant, spec in VARIANTS.items():
        path = root / spec["path"]
        text = render(variant, root)
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            written.append(spec["path"])
    return written
