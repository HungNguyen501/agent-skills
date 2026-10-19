"""Copy a chosen set of hub skills into a consumer repo (run at build time).

Consumer config (skills.toml):

    [hub]
    ref = "v0.1.0"                 # informational; pin the checkout itself in git
    [skills]
    include = ["databricks-billing-queries", "databricks-scope-filters"]

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hub", required=True, type=Path, help="path to a checkout of the hub")
    parser.add_argument("--config", required=True, type=Path, help="consumer skills.toml")
    parser.add_argument("--dest", required=True, type=Path, help="directory to copy skills into")
    args = parser.parse_args()

    config = tomllib.loads(args.config.read_text(encoding="utf-8"))
    wanted = config.get("skills", {}).get("include", [])
    if not wanted:
        print("error: skills.include is empty in config")
        return 1

    manifest = json.loads((args.hub / "manifest.json").read_text(encoding="utf-8"))
    by_name = {s["name"]: s for s in manifest["skills"]}
    unknown = [n for n in wanted if n not in by_name]
    if unknown:
        print(f"error: not in hub manifest: {', '.join(unknown)}. Available: {', '.join(sorted(by_name))}")
        return 1

    if args.dest.exists():
        shutil.rmtree(args.dest)
    args.dest.mkdir(parents=True)
    for name in wanted:
        shutil.copytree(
            args.hub / by_name[name]["path"], args.dest / name, ignore=shutil.ignore_patterns("evals", "__pycache__")
        )

    sha = subprocess.run(
        ["git", "-C", str(args.hub), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    (args.dest / ".hub-version").write_text(f"{sha or 'unknown'}\n", encoding="utf-8")
    print(f"synced {len(wanted)} skill(s) from hub {sha[:7] or 'unknown'} into {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
