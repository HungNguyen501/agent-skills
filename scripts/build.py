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


def generate(out: Path) -> None:
    domains = json.loads((skilllib.SKILLS_DIR / "domains.json").read_text(encoding="utf-8"))
    skills = [skilllib.load(p) for p in skilllib.discover()]

    manifest = []
    plugins = []
    for domain in sorted({s.domain for s in skills}):
        plugin_dir = out / "plugins" / domain
        (plugin_dir / ".claude-plugin").mkdir(parents=True)
        (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
            json.dumps(
                {
                    "name": domain,
                    "description": domains[domain],
                    "version": META["version"],
                    "license": META["license"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        plugins.append({"name": domain, "source": f"./plugins/{domain}", "description": domains[domain]})

    for skill in skills:
        dest = out / "plugins" / skill.domain / "skills" / skill.path.name
        shutil.copytree(skill.path, dest, ignore=shutil.ignore_patterns("evals", "__pycache__"))
        manifest.append(
            {
                "name": skill.name,
                "domain": skill.domain,
                "description": skill.meta["description"],
                "always": skill.always,
                "order": skill.order,
                "path": f"skills/{skill.domain}/{skill.path.name}",
                "tokens": skilllib.estimate_tokens(skill.body),
            }
        )

    (out / ".claude-plugin").mkdir(exist_ok=True)
    (out / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(
            {"name": META["name"], "owner": {"name": META["owner"]}, "plugins": plugins},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "manifest.json").write_text(
        json.dumps({"version": META["version"], "skills": manifest}, indent=2) + "\n", encoding="utf-8"
    )


def _same(a: Path, b: Path) -> bool:
    if a.is_file() or b.is_file():
        return a.is_file() and b.is_file() and filecmp.cmp(a, b, shallow=False)
    if not (a.is_dir() and b.is_dir()):
        return False
    cmp = filecmp.dircmp(a, b)
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
