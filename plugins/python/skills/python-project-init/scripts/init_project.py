#!/usr/bin/env python3
"""Creates a new Python project from the bundled templates.

Usage: init_project.py DEST --name NAME [options] [--apply]

Without --apply it prints the plan and writes nothing. It never overwrites: if any
target file already exists it reports every conflict, writes nothing and exits 1.
Standard library only (Python 3.9+).
"""

from __future__ import annotations

import argparse
import keyword
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"

TOKEN_RE = re.compile(r"@@(\w+)@@")
NAME_RE = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")  # used with fullmatch
# Used with fullmatch: "$" would also accept a trailing newline.
PYTHON_RE = re.compile(r"3\.([1-9]\d?)")
# Python 3.9 reached end of life in October 2025, so older targets are rejected.
MIN_MINOR = 10
# Newest release the generated ruff target, mypy settings and CI were run against. The version goes into ruff's
# target-version as py3<minor>, which ruff rejects when it does not know the release, so raise this only after
# checking a newer one.
MAX_MINOR = 14
# Names that would shadow or clash with the project's own top-level folders.
RESERVED_PACKAGES = {"src", "tests"}
# Google style says 80. Both team repos use longer lines, so the default follows them. The bounds catch typos.
LINE_LENGTH_MIN, LINE_LENGTH_MAX = 80, 200

# hatchling is the build backend of the Microsoft and Apple projects reviewed. It needs the package path in src/ layouts.
LIB_BUILD_SYSTEM = (
    '\n[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
    '\n[tool.hatch.build.targets.wheel]\npackages = ["src/{package}"]\n'
)


@dataclass
class Action:
    """One file to create."""

    dest: str
    content: bytes
    executable: bool = False


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parses and validates the command line."""
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("dest", type=Path, help="project directory (created if missing)")
    p.add_argument("--name", required=True, help="project name, lowercase with hyphens, e.g. order-sync")
    p.add_argument("--package", help="import package name (default: name with underscores)")
    p.add_argument("--description", help="one-line description")
    p.add_argument("--python", default="3.12", help="minimum Python version (default: 3.12)")
    p.add_argument("--line-length", type=int, default=140, help="ruff line length (default: 140)")
    p.add_argument("--layout", choices=("app", "lib"), default="app", help="app: src/ is the import root. lib: src/<package>/, installable")
    p.add_argument("--apply", action="store_true", help="write the files (default: print the plan only)")
    args = p.parse_args(argv)

    if not NAME_RE.fullmatch(args.name):
        p.error(f"--name must be lowercase letters, digits and single hyphens, got {args.name!r}")
    args.package = args.package or args.name.replace("-", "_")
    if not args.package.isidentifier() or args.package != args.package.lower() or args.package.startswith("_"):
        p.error(f"--package must be a lowercase Python identifier, got {args.package!r}")
    if keyword.iskeyword(args.package) or args.package in RESERVED_PACKAGES:
        p.error(f"--package {args.package!r} is a Python keyword or a reserved folder name (src, tests)")
    version = PYTHON_RE.fullmatch(args.python)
    if not version or not MIN_MINOR <= int(version.group(1)) <= MAX_MINOR:
        p.error(f"--python must be one of 3.{MIN_MINOR} to 3.{MAX_MINOR}, got {args.python!r}")
    if not LINE_LENGTH_MIN <= args.line_length <= LINE_LENGTH_MAX:
        p.error(f"--line-length must be between {LINE_LENGTH_MIN} and {LINE_LENGTH_MAX}")
    args.description = args.description or f"{args.name} Python project"
    if re.search(r'["\\\x00-\x1f\x7f]', args.description):
        p.error("--description must not contain quotes, backslashes or control characters (it goes into TOML)")
    return args


def build_tokens(args: argparse.Namespace) -> dict[str, str]:
    """Returns the values substituted for @@token@@ in the templates."""
    lib = args.layout == "lib"
    src_dir = f"src/{args.package}" if lib else "src"
    tree = [
        f"{args.name}/",
        f"├── {src_dir}/" + ("   source code, imported as `" + args.package + "`" if lib else "   source code, imported as `src.<module>`"),
        "├── tests/       mirrors the source tree",
        "├── scripts/     ci.sh",
        "├── configs/     pre-commit and yamllint config",
        "├── .github/     CI workflow, PR and commit templates",
    ]
    tree += ["├── AGENTS.md", "├── Makefile", "└── pyproject.toml"]
    return {
        "name": args.name,
        "package": args.package,
        "description": args.description,
        "python": args.python,
        "ruff_target": "py" + args.python.replace(".", ""),
        "line_length": str(args.line_length),
        "import_root": args.package if lib else "src",
        "first_party": f'["{args.package}", "tests"]' if lib else '["src", "tests"]',
        "pythonpath": '["src"]' if lib else '["."]',
        "uv_package": "true" if lib else "false",
        "build_system": LIB_BUILD_SYSTEM.format(package=args.package) if lib else "",
        "example_path": f"{src_dir}/example.py",
        "src_hint": src_dir,
        "structure": "```text\n" + "\n".join(tree) + "\n```",
    }


def render(template: Path, tokens: dict[str, str]) -> bytes:
    """Fills the @@token@@ placeholders. An unknown token is a template bug and aborts."""
    text = template.read_text(encoding="utf-8")

    def sub(match: re.Match) -> str:
        key = match.group(1)
        if key not in tokens:
            raise SystemExit(f"error: unknown token @@{key}@@ in {template}")
        return tokens[key]

    return TOKEN_RE.sub(sub, text).encode("utf-8")


def template_actions(pairs: list[tuple[str, str]], tokens: dict[str, str]) -> list[Action]:
    """Renders (asset path, destination) pairs. The CI shell script becomes executable."""
    actions = []
    for asset, dest in pairs:
        src = ASSETS / asset
        if not src.is_file():
            raise SystemExit(f"error: missing template {src}")
        actions.append(Action(dest, render(src, tokens), executable=dest.endswith(".sh")))
    return actions


def build_plan(args: argparse.Namespace) -> list[Action]:
    """Returns every file to create."""
    tokens = build_tokens(args)
    src_dir = tokens["src_hint"]
    pairs = [
        ("project/pyproject.toml.tmpl", "pyproject.toml"),
        ("project/Makefile.tmpl", "Makefile"),
        ("project/gitignore.tmpl", ".gitignore"),
        ("project/env.example.tmpl", ".env.example"),
        ("project/README.md.tmpl", "README.md"),
        ("project/AGENTS.md.tmpl", "AGENTS.md"),
        ("project/scripts/ci.sh.tmpl", "scripts/ci.sh"),
        ("project/configs/pre-commit-config.yaml.tmpl", "configs/.pre-commit-config.yaml"),
        ("project/configs/yamllint.tmpl", "configs/.yamllint"),
        ("project/github/workflows/ci.yaml.tmpl", ".github/workflows/ci.yaml"),
        ("project/github/pull_request_template.md.tmpl", ".github/pull_request_template.md"),
        ("project/github/commit_template.md.tmpl", ".github/commit_template.md"),
        ("project/python/init.py.tmpl", f"{src_dir}/__init__.py"),
        ("project/python/example.py.tmpl", f"{src_dir}/example.py"),
        ("project/python/tests_init.py.tmpl", "tests/__init__.py"),
        ("project/python/test_example.py.tmpl", "tests/test_example.py"),
    ]
    if args.layout == "lib":
        pairs.append(("project/python/py.typed.tmpl", f"{src_dir}/py.typed"))
    return template_actions(pairs, tokens)


def conflict_reason(path: Path) -> str | None:
    """Why `path` cannot be created, or None. Catches an existing file or link and a parent that is not a directory."""
    if path.exists() or path.is_symlink():
        return "already exists"
    for parent in path.parents:
        if parent.exists() or parent.is_symlink():
            return None if parent.is_dir() else f"{parent.name} is not a directory"
    return None


def find_conflicts(dest: Path, actions: list[Action]) -> dict[str, str]:
    """Maps each destination path that cannot be created to the reason."""
    paths = [a.dest for a in actions]
    if len(paths) != len(set(paths)):
        dupes = sorted({p for p in paths if paths.count(p) > 1})
        raise SystemExit(f"error: plan writes the same path twice: {', '.join(dupes)}")
    return {a.dest: reason for a in actions if (reason := conflict_reason(dest / a.dest))}


def print_plan(args: argparse.Namespace, dest: Path, actions: list[Action], conflicts: dict[str, str]) -> None:
    """Prints the settings and one line per file."""
    print(f"Project: {args.name}  package: {args.package}  layout: {args.layout}  python: >={args.python}  line length: {args.line_length}")
    print(f"Destination: {dest}")
    for action in actions:
        reason = conflicts.get(action.dest)
        print(f"  {'conflict' if reason else 'create  '} {action.dest}" + (f" ({reason})" if reason else ""))


def write_actions(dest: Path, actions: list[Action]) -> None:
    """Writes every file. Raises OSError, which can leave a partly written project."""
    for action in actions:
        target = dest / action.dest
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(action.content)
        if action.executable:
            target.chmod(0o755)


def main(argv: list[str]) -> int:
    """Prints the plan and, with --apply and no conflicts, writes the files."""
    args = parse_args(argv)
    dest: Path = args.dest.expanduser().resolve()
    if dest.exists() and not dest.is_dir():
        print(f"error: {dest} exists and is not a directory", file=sys.stderr)
        return 1
    actions = build_plan(args)
    conflicts = find_conflicts(dest, actions)
    print_plan(args, dest, actions, conflicts)
    if conflicts:
        print(f"\n{len(conflicts)} path(s) cannot be created. Nothing written. Pick another directory or remove or merge them by hand.")
        return 1
    if not args.apply:
        print(f"\nDry run: {len(actions)} file(s) would be created. Re-run with --apply to write them.")
        return 0
    try:
        write_actions(dest, actions)
    except OSError as error:
        print(f"error: {error}. The project may be partly written in {dest}.", file=sys.stderr)
        return 1
    print(f"\nCreated {len(actions)} file(s) in {dest}.")
    print("Next: install the hub's python skills into the project (SKILL.md, step 4).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
