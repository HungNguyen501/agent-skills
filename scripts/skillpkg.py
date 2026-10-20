"""Packaging rules shared by build.py and validate.py: what is copied, and which symlinks matter."""
from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path

# Names left out of packaged skills (matched at any depth).
PACKAGE_IGNORE = ("evals", "__pycache__")


def ignore_patterns() -> Callable[[str, list[str]], set[str]]:
    """The `ignore=` argument for shutil.copytree when packaging a skill."""
    return shutil.ignore_patterns(*PACKAGE_IGNORE)


def find_symlinks(root: Path) -> list[Path]:
    """Every symlink under `root` that packaging would copy.

    Names in PACKAGE_IGNORE are skipped with the same predicate copytree uses, so a link in a path that is
    never copied is not reported. Symlinked directories are listed and never descended into.
    """
    ignore = ignore_patterns()
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        skipped = ignore(dirpath, dirnames + filenames)
        dirnames[:] = [d for d in dirnames if d not in skipped]
        found += [
            Path(dirpath) / name
            for name in dirnames + [f for f in filenames if f not in skipped]
            if (Path(dirpath) / name).is_symlink()
        ]
    return found
