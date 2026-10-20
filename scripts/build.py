"""Generate plugins/ and .claude-plugin/marketplace.json from skills/.

Never edit the generated files by hand. CI runs this and fails if the tree changes.
Pass --check to verify without writing.
"""
from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import skilllib
import skillpkg

ROOT = skilllib.ROOT
OUTPUTS = ("plugins", ".claude-plugin")
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


def ensure_packageable(skill_dir: Path) -> None:
    """Raise ValueError unless copying `skill_dir` stays inside it.

    copytree follows symlinks, so a link would copy files from outside the skill into distributable output,
    or fail on a loop. This checks the skill and domain directories, then every link in a path that is
    packaged. Links in excluded paths (evals, __pycache__) are ignored, because they are never copied.
    """
    problems = [f"{path} is a symlinked {label}" for path, label in skillpkg.root_links(skill_dir)]
    if not problems:
        problems = [f"{path} is a symlink" for path in skillpkg.find_symlinks(skill_dir)]
    if problems:
        raise ValueError(f"refusing to package {skill_dir.name}: {'; '.join(problems)}")


def package_skill(out: Path, skill: skilllib.Skill) -> None:
    """Copy a skill into its domain plugin, leaving out evals and caches. Raises ValueError if it contains symlinks."""
    ensure_packageable(skill.path)
    dest = out / "plugins" / skill.domain / "skills" / skill.path.name
    shutil.copytree(skill.path, dest, ignore=skillpkg.ignore_patterns())


def generate(out: Path) -> None:
    """Coordinate the build: per-domain plugins, packaged skills and the marketplace."""
    domains = skilllib.load_domains()
    skill_dirs = skilllib.discover()
    for skill_dir in skill_dirs:
        ensure_packageable(skill_dir)  # before SKILL.md is read, which would read through a linked skill or domain directory
    skills = [skilllib.load(p) for p in skill_dirs]
    unregistered = sorted({s.domain for s in skills} - domains.keys())
    if unregistered:
        raise ValueError(f"domain(s) missing from skills/domains.json: {', '.join(unregistered)}")

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


def _owner_exec(path: Path) -> bool | None:
    """The executable bit git tracks (owner), which copytree preserves, so a chmod-only change means the packaged
    script is wrong. Group and other bits are not tracked by git, so they are ignored. None where the filesystem
    has no meaningful exec bit (Windows), which makes the comparison a no-op there."""
    if os.name == "nt":
        return None
    return bool(path.stat().st_mode & 0o100)


def _same(a: Path, b: Path) -> bool:
    """Whether two trees are identical. A symlink on either side is a difference: is_file(), is_dir() and the content
    comparison all follow links, and generated output never contains them, so a link would hide a broken artifact."""
    if a.is_symlink() or b.is_symlink():
        return False
    if a.is_file() or b.is_file():
        if not (a.is_file() and b.is_file()):
            return False
        return filecmp.cmp(a, b, shallow=False) and _owner_exec(a) == _owner_exec(b)
    if not (a.is_dir() and b.is_dir()):
        return False
    # ignore=[] because dircmp's default list skips names such as `tags` and `.git`, which packaging does copy.
    cmp = filecmp.dircmp(a, b, ignore=[])
    if cmp.left_only or cmp.right_only or cmp.funny_files:
        return False
    return all(_same(a / n, b / n) for n in cmp.common)


def install_outputs(fresh: Path, root: Path) -> None:
    """Replace each output under `root` with the freshly generated one from `fresh`.

    A symlink at an output root, live or dangling, is removed as a link first. is_dir() follows links, so
    rmtree() would raise on it, and a dangling link is not seen by exists() and would block the move. The
    directory a live link points at is left untouched.
    """
    for name in OUTPUTS:
        target = root / name
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        shutil.move(str(fresh / name), str(target))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated files are stale")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp)
        try:
            generate(fresh)
        except (ValueError, OSError) as exc:
            print(f"error: {exc}")
            return 1
        if args.check:
            stale = [n for n in OUTPUTS if not _same(fresh / n, ROOT / n)]
            if stale:
                print(f"stale generated files: {', '.join(stale)}. Run: uv run python scripts/build.py")
                return 1
            print("generated files are up to date")
            return 0
        install_outputs(fresh, ROOT)
    print(f"generated {', '.join(OUTPUTS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
