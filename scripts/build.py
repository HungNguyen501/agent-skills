"""Generate plugins/, .claude-plugin/marketplace.json and manifest.json from skills/.

Never edit the generated files by hand. CI runs this and fails if the tree changes.
Pass --check to verify without writing.
"""
from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import sys
import tempfile
from pathlib import Path

import skilllib

ROOT = skilllib.ROOT
OUTPUTS = ("plugins", ".claude-plugin", "manifest.json")
META = json.loads((ROOT / "hub.json").read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_plugin_manifest(out: Path, domain: str, description: str) -> dict:
    """Write plugins/<domain>/.claude-plugin/plugin.json and return the marketplace entry."""
    _write_json(
        out / "plugins" / domain / ".claude-plugin" / "plugin.json",
        {"name": domain, "description": description, "version": META["version"], "license": META["license"]},
    )
    return {"name": domain, "source": f"./plugins/{domain}", "description": description}


def package_skill(out: Path, skill: skilllib.Skill) -> None:
    """Copy a skill into its domain plugin, leaving out evals and caches."""
    dest = out / "plugins" / skill.domain / "skills" / skill.path.name
    shutil.copytree(skill.path, dest, ignore=shutil.ignore_patterns(*skilllib.PACKAGE_IGNORE))


def manifest_entry(skill: skilllib.Skill) -> dict:
    return {
        "name": skill.name,
        "domain": skill.domain,
        "description": skill.meta["description"],
        "always": skill.always,
        "order": skill.order,
        "path": f"skills/{skill.domain}/{skill.path.name}",
        "tokens": skilllib.estimate_tokens(skill.body),
    }


def generate(out: Path) -> None:
    """Coordinate the build: per-domain plugins, packaged skills, marketplace and manifest."""
    domains = json.loads((skilllib.SKILLS_DIR / "domains.json").read_text(encoding="utf-8"))
    skills = [skilllib.load(p) for p in skilllib.discover()]

    # Always create every output directory, so an empty skill collection still builds and checks cleanly.
    (out / "plugins").mkdir(parents=True, exist_ok=True)
    (out / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    plugins = [write_plugin_manifest(out, d, domains[d]) for d in sorted({s.domain for s in skills})]
    for skill in skills:
        package_skill(out, skill)

    _write_json(
        out / ".claude-plugin" / "marketplace.json",
        {"name": META["name"], "owner": {"name": META["owner"]}, "plugins": plugins},
    )
    _write_json(out / "manifest.json", {"version": META["version"], "skills": [manifest_entry(s) for s in skills]})


def _same(a: Path, b: Path) -> bool:
    if a.is_file() or b.is_file():
        return a.is_file() and b.is_file() and filecmp.cmp(a, b, shallow=False)
    if not (a.is_dir() and b.is_dir()):
        return False
    # ignore=[] because dircmp's default list skips names such as `tags` and `.git`, which packaging does copy.
    cmp = filecmp.dircmp(a, b, ignore=[])
    if cmp.left_only or cmp.right_only or cmp.funny_files:
        return False
    return all(_same(a / n, b / n) for n in cmp.common)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated files are stale")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp)
        generate(fresh)
        if args.check:
            stale = [n for n in OUTPUTS if not _same(fresh / n, ROOT / n)]
            if stale:
                print(f"stale generated files: {', '.join(stale)}. Run: uv run python scripts/build.py")
                return 1
            print("generated files are up to date")
            return 0
        for name in OUTPUTS:
            target = ROOT / name
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            shutil.move(str(fresh / name), str(target))
    print(f"generated {', '.join(OUTPUTS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
