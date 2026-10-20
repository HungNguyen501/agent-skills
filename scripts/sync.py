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
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


# Names left out of synced skills. Keep identical to PACKAGE_IGNORE in scripts/skilllib.py; this script
# stays stdlib-only so it can run from a bare hub checkout. tests/test_hub.py asserts they match.
PACKAGE_IGNORE = ("evals", "__pycache__")


def read_manifest_skills(manifest: object) -> list[dict]:
    """Return manifest["skills"] after checking its shape. Raises ValueError for a malformed manifest."""
    skills = manifest.get("skills") if isinstance(manifest, dict) else None
    if not isinstance(skills, list) or not all(
        isinstance(s, dict) and isinstance(s.get("name"), str) and isinstance(s.get("path"), str) for s in skills
    ):
        raise ValueError("hub manifest.json is malformed: expected a 'skills' list of objects with string 'name' and 'path'")
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


def stage(hub: Path, manifest: dict, wanted: list[str], staging: Path) -> None:
    """Copy the selected skills and a revision marker into a fresh staging directory."""
    by_name = {s["name"]: s for s in read_manifest_skills(manifest)}
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for name in wanted:
        shutil.copytree(hub / by_name[name]["path"], staging / name, ignore=shutil.ignore_patterns(*PACKAGE_IGNORE))
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
        args.dest.parent.mkdir(parents=True, exist_ok=True)
        stage(args.hub, manifest, wanted, staging)
        replace_dest(staging, args.dest)
    except (ValueError, OSError, tomllib.TOMLDecodeError, json.JSONDecodeError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        print(f"error: {exc}")
        return 1

    print(f"synced {len(wanted)} skill(s) from hub {hub_revision(args.hub)[:7]} into {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
