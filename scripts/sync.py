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


def read_selection(config_path: Path, manifest: dict) -> list[str]:
    """Return the deduplicated, validated skill names from the consumer config. Raises ValueError."""
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    include = config.get("skills", {}).get("include", [])
    if not isinstance(include, list) or not all(isinstance(n, str) for n in include):
        raise ValueError("skills.include must be a list of skill names")
    wanted = list(dict.fromkeys(include))
    if not wanted:
        raise ValueError("skills.include is empty in config")
    available = {s["name"] for s in manifest["skills"]}
    unknown = [n for n in wanted if n not in available]
    if unknown:
        raise ValueError(f"not in hub manifest: {', '.join(unknown)}. Available: {', '.join(sorted(available))}")
    return wanted


def hub_revision(hub: Path) -> str:
    result = subprocess.run(["git", "-C", str(hub), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return result.stdout.strip() or "unknown"


def stage(hub: Path, manifest: dict, wanted: list[str], staging: Path) -> None:
    """Copy the selected skills and a revision marker into a fresh staging directory."""
    by_name = {s["name"]: s for s in manifest["skills"]}
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for name in wanted:
        shutil.copytree(hub / by_name[name]["path"], staging / name, ignore=shutil.ignore_patterns("evals", "__pycache__"))
    (staging / ".hub-version").write_text(f"{hub_revision(hub)}\n", encoding="utf-8")


def replace_dest(staging: Path, dest: Path) -> None:
    """Swap the staged directory into place, keeping the old one until the swap succeeds."""
    backup = dest.with_name(f".{dest.name}.old")
    if backup.exists():
        shutil.rmtree(backup)
    if dest.exists():
        dest.rename(backup)
    try:
        staging.rename(dest)
    except OSError:
        if backup.exists():
            backup.rename(dest)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hub", required=True, type=Path, help="path to a checkout of the hub")
    parser.add_argument("--config", required=True, type=Path, help="consumer skills.toml")
    parser.add_argument("--dest", required=True, type=Path, help="directory to copy skills into")
    args = parser.parse_args()

    staging = args.dest.with_name(f".{args.dest.name}.staging")
    try:
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
