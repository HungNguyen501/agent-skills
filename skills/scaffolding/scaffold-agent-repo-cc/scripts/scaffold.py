"""Installs hub skills into a destination repo in the Claude Code layout.

Usage: scaffold.py --hub HUB_DIR --dest DEST_DIR --skills NAME[,NAME...] [--dry-run] [--force]

Resolves each name to HUB_DIR/skills/<domain>/<name>, copies it to DEST_DIR/.claude/skills/<name>/ without evals/ and
caches, writes DEST_DIR/CLAUDE.md if absent, and records what was installed in
DEST_DIR/.claude/skills/.hub-skills.json. Also writes .claude/settings.example.json and ignores .claude/settings.local.json.
Nothing is written when any name is unknown or any destination skill exists (unless --force). Exit status is 1 on error.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SKILLS_DIR = ".claude/skills"
INSTRUCTIONS = "CLAUDE.md"
# Names left out of copies: evals are test fixtures, not agent-facing content.
IGNORE = shutil.ignore_patterns("evals", "__pycache__")
INSTRUCTIONS_TEMPLATE = """# {project}

<!-- Describe the project, its commands and its rules here. Keep this file short. -->

## Skills

Installed from the agent-skills hub (see `{skills_dir}/.hub-skills.json`):

{skill_lines}
"""

# Local overrides must never be committed; only the example file is.
GITIGNORE_LINE = ".claude/settings.local.json"
SETTINGS_EXAMPLE = {"permissions": {"allow": [], "deny": []}}


def write_claude_extras(dest):
    """Writes .claude/settings.example.json if absent and ignores settings.local.json in .gitignore."""
    example = dest / ".claude" / "settings.example.json"
    if not example.exists():
        example.write_text(json.dumps(SETTINGS_EXAMPLE, indent=2) + "\n", encoding="utf-8")
    gitignore = dest / ".gitignore"
    text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if GITIGNORE_LINE not in text.splitlines():
        gitignore.write_text(text + ("" if text.endswith("\n") or not text else "\n") + GITIGNORE_LINE + "\n", encoding="utf-8")


def find_skills(hub):
    """Maps skill name to directory for every skills/<domain>/<name>/SKILL.md under the hub."""
    return {p.parent.name: p.parent for p in sorted((hub / "skills").glob("*/*/SKILL.md"))}


def describe(skill_dir):
    """Returns the one-line description from a SKILL.md frontmatter, or an empty string."""
    for line in (skill_dir / "SKILL.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip()[:120]
    return ""


def hub_revision(hub):
    """Returns the hub's git SHA, or 'unknown' when the hub is not a git checkout."""
    try:
        out = subprocess.run(["git", "-C", str(hub), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def has_symlink(path):
    """True when `path` or anything under it is a symlink, which would copy files from outside the skill."""
    return path.is_symlink() or any(p.is_symlink() for p in path.rglob("*"))


def plan(hub, dest, names, force):
    """Returns (errors, actions) without touching the destination."""
    available = find_skills(hub)
    errors, actions = [], []
    for name in names:
        if name not in available:
            errors.append(f"Skill `{name}` not found. Available: {', '.join(available) or '(none)'}")
        elif has_symlink(available[name]):
            errors.append(f"Skill `{name}` contains a symlink; refusing to copy")
        elif (dest / SKILLS_DIR / name).exists() and not force:
            errors.append(f"{dest / SKILLS_DIR / name} exists; pass --force to replace it")
        else:
            actions.append((name, available[name], dest / SKILLS_DIR / name))
    return errors, actions


def main(argv=None):
    """Parses arguments, prints the plan and, unless --dry-run, applies it."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hub", type=Path, required=True, help="path to the agent-skills hub checkout")
    ap.add_argument("--dest", type=Path, required=True, help="destination repo")
    ap.add_argument("--skills", required=True, help="comma-separated hub skill names")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    ap.add_argument("--force", action="store_true", help="replace skills that already exist in the destination")
    args = ap.parse_args(argv)

    names = [n.strip() for n in args.skills.split(",") if n.strip()]
    if not (args.hub / "skills").is_dir():
        print(f"error: {args.hub} has no skills/ directory", file=sys.stderr)
        return 1
    if not args.dest.is_dir():
        print(f"error: destination {args.dest} is not a directory", file=sys.stderr)
        return 1
    errors, actions = plan(args.hub, args.dest, names, args.force)
    if errors:
        print("\n".join(f"error: {e}" for e in errors), file=sys.stderr)
        return 1

    instructions = args.dest / INSTRUCTIONS
    for name, src, target in actions:
        print(f"copy {src} -> {target}")
    print(f"{'keep existing' if instructions.exists() else 'write'} {instructions}")
    if args.dry_run:
        print("dry run: nothing written")
        return 0

    # Stage every copy first so a failed copy never removes a skill that is already installed.
    staged = []
    try:
        for name, src, target in actions:
            staging = target.with_name(f".{name}.new")
            if staging.exists():
                shutil.rmtree(staging)
            staged.append((staging, target))
            shutil.copytree(src, staging, ignore=IGNORE)
    except Exception:
        for staging, _ in staged:
            shutil.rmtree(staging, ignore_errors=True)
        raise
    for staging, target in staged:
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    manifest_path = args.dest / SKILLS_DIR / ".hub-skills.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"skills": []}
    manifest["hub_revision"] = hub_revision(args.hub)
    # Drop entries whose folder was deleted, so the manifest lists only what is installed.
    still_installed = {n for n in manifest["skills"] if (args.dest / SKILLS_DIR / n).is_dir()}
    manifest["skills"] = sorted(still_installed | {n for n, _, _ in actions})
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if not instructions.exists():
        lines = "\n".join(f"- `{n}`: {describe(args.hub / 'skills' / _domain(args.hub, n) / n)}" for n in manifest["skills"])
        instructions.write_text(
            INSTRUCTIONS_TEMPLATE.format(project=args.dest.resolve().name, skills_dir=SKILLS_DIR, skill_lines=lines),
            encoding="utf-8")
    write_claude_extras(args.dest)
    print(f"installed {len(actions)} skill(s) into {args.dest / SKILLS_DIR}")
    return 0


def _domain(hub, name):
    """Returns the domain directory name that holds skill `name`."""
    return find_skills(hub)[name].parent.name


if __name__ == "__main__":
    sys.exit(main())
