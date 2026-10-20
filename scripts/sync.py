"""Copy a chosen set of hub skills into a consumer repo (run at build time).

Consumer config (skills.toml):

    [hub]
    ref = "v0.1.0"                 # informational; pin the checkout itself in git
    [skills]
    include = ["databricks-billing-queries", "databricks-scope-filters"]

The destination is replaced only after every skill has been staged successfully, so a bad
config or a failed copy never leaves the consumer with a partial or empty skill set.

Usage:
    python sync.py --hub path/to/agent-skills --config skills.toml --dest src/worker/skills
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath


# Names left out of synced skills. Keep identical to PACKAGE_IGNORE in scripts/skilllib.py; this script
# stays stdlib-only so it can run from a bare hub checkout. tests/test_hub.py asserts they match.
PACKAGE_IGNORE = ("evals", "__pycache__")


# A skill name is used as a directory name in the consumer, so it must be one safe path component.
# Same rule as NAME_RE in scripts/validate.py.
SAFE_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def read_manifest_skills(manifest: object) -> list[dict]:
    """Return manifest["skills"] after checking its shape, names and paths. Raises ValueError.

    Names must be single safe directory names and unique. Paths must be relative with no `..` part;
    resolve_sources() then enforces that they stay inside the hub.
    """
    skills = manifest.get("skills") if isinstance(manifest, dict) else None
    if not isinstance(skills, list) or not all(
        isinstance(s, dict) and isinstance(s.get("name"), str) and isinstance(s.get("path"), str) for s in skills
    ):
        raise ValueError("hub manifest.json is malformed: expected a 'skills' list of objects with string 'name' and 'path'")
    seen: set[str] = set()
    for entry in skills:
        name, path = entry["name"], PurePosixPath(entry["path"])
        if len(name) > 64 or not SAFE_NAME.fullmatch(name):
            raise ValueError(f"hub manifest.json lists unsafe skill name {name!r}: expected lowercase letters, digits and hyphens")
        if name in seen:
            raise ValueError(f"hub manifest.json lists skill name {name!r} more than once")
        seen.add(name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError(f"hub manifest.json has an unsafe path for skill {name!r}: {entry['path']!r}")
    return skills


def read_selection(config_path: Path, manifest: dict) -> list[str]:
    """Return the deduplicated, validated skill names from the consumer config. Raises ValueError."""
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    section = config.get("skills")
    if not isinstance(section, dict):
        raise ValueError("config needs a [skills] table with an include list")
    include = section.get("include", [])
    if not isinstance(include, list) or not all(isinstance(n, str) for n in include):
        raise ValueError("skills.include must be a list of skill names")
    wanted = list(dict.fromkeys(include))
    if not wanted:
        raise ValueError("skills.include is empty in config")
    available = {s["name"] for s in read_manifest_skills(manifest)}
    unknown = [n for n in wanted if n not in available]
    if unknown:
        raise ValueError(f"not in hub manifest: {', '.join(unknown)}. Available: {', '.join(sorted(available))}")
    return wanted


def hub_revision(hub: Path) -> str:
    result = subprocess.run(["git", "-C", str(hub), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return result.stdout.strip() or "unknown"


def resolve_sources(hub: Path, manifest: dict, wanted: list[str]) -> list[tuple[str, Path]]:
    """Resolve each selected skill to its source directory, which must be a skill inside the hub's skills/.

    Runs before anything is created, so a bad manifest cannot write or read outside the hub.
    Raises ValueError.
    """
    by_name = {s["name"]: s for s in read_manifest_skills(manifest)}
    skills_root = (hub.resolve() / "skills").resolve()
    sources: list[tuple[str, Path]] = []
    for name in wanted:
        source = (hub.resolve() / by_name[name]["path"]).resolve()
        if not source.is_relative_to(skills_root) or not (source / "SKILL.md").is_file():
            raise ValueError(f"skill {name!r}: path {by_name[name]['path']!r} is not a skill directory inside the hub's skills/")
        sources.append((name, source))
    return sources


def stage(hub: Path, sources: list[tuple[str, Path]], staging: Path) -> None:
    """Copy the resolved skills and a revision marker into a fresh staging directory."""
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    staging_root = staging.resolve()
    for name, source in sources:
        target = staging / name
        if target.resolve().parent != staging_root:  # defence in depth; names are validated already
            raise ValueError(f"skill {name!r} would be written outside the staging directory")
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(*PACKAGE_IGNORE))
    (staging / ".hub-version").write_text(f"{hub_revision(hub)}\n", encoding="utf-8")


def backup_path(dest: Path) -> Path:
    return dest.with_name(f".{dest.name}.old")


def recover_interrupted_swap(dest: Path) -> None:
    """Heal the state a crashed run can leave behind. Safe to call at any time.

    A run that died between `dest -> backup` and `staging -> dest` leaves no dest and the previous
    skills only in the backup, so the backup is restored. When dest exists, any backup is a stale
    leftover of a swap that did finish, so it is removed.
    """
    backup = backup_path(dest)
    if not backup.exists():
        return
    if dest.exists():
        shutil.rmtree(backup)
    else:
        backup.rename(dest)


def replace_dest(staging: Path, dest: Path) -> None:
    """Swap the staged directory into place. The old copy is deleted only after the swap succeeds."""
    recover_interrupted_swap(dest)  # after this, a backup never exists while dest is missing
    backup = backup_path(dest)
    had_dest = dest.exists()
    if had_dest:
        dest.rename(backup)
    try:
        staging.rename(dest)
    except OSError:
        if had_dest:
            backup.rename(dest)
        raise
    if had_dest:
        shutil.rmtree(backup)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hub", required=True, type=Path, help="path to a checkout of the hub")
    parser.add_argument("--config", required=True, type=Path, help="consumer skills.toml")
    parser.add_argument("--dest", required=True, type=Path, help="directory to copy skills into")
    args = parser.parse_args()

    staging = args.dest.with_name(f".{args.dest.name}.staging")
    try:
        recover_interrupted_swap(args.dest)  # first, so a failed run below cannot leave dest missing
        manifest = json.loads((args.hub / "manifest.json").read_text(encoding="utf-8"))
        wanted = read_selection(args.config, manifest)
        sources = resolve_sources(args.hub, manifest, wanted)  # validates everything before anything is created
        args.dest.parent.mkdir(parents=True, exist_ok=True)
        stage(args.hub, sources, staging)
        replace_dest(staging, args.dest)
    except (ValueError, OSError, tomllib.TOMLDecodeError, json.JSONDecodeError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        print(f"error: {exc}")
        return 1

    print(f"synced {len(wanted)} skill(s) from hub {hub_revision(args.hub)[:7]} into {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
