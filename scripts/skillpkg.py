"""Packaging rules shared by build.py and validate.py: what is copied, and which symlinks matter."""
from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

# Names left out of packaged skills (matched at any depth).
PACKAGE_IGNORE = ("evals", "__pycache__")


def ignore_patterns() -> Callable[[str, list[str]], set[str]]:
    """The `ignore=` argument for shutil.copytree when packaging a skill."""
    return shutil.ignore_patterns(*PACKAGE_IGNORE)


def walk_packaged(root: Path) -> Iterator[tuple[Path, list[str], list[str]]]:
    """os.walk over `root` that skips what packaging skips: yields (directory, subdirectory names, file names).

    PACKAGE_IGNORE names are pruned at every depth with the same predicate copytree uses, and symlinked
    directories are listed but never descended into. This is the single definition of "what gets packaged".

    A `root` that is itself a symlink yields nothing: os.walk(followlinks=False) only stops at links below its
    starting point, so without this check a linked root would be traversed, and read, from its target. Callers that
    need to reject a linked root report it themselves (validate.check_roots, and check_symlinks for subdirectories).
    """
    if root.is_symlink():
        return
    ignore = ignore_patterns()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        skipped = ignore(dirpath, dirnames + filenames)
        dirnames[:] = [d for d in dirnames if d not in skipped]
        yield Path(dirpath), dirnames, [f for f in filenames if f not in skipped]


def find_symlinks(root: Path) -> list[Path]:
    """Every symlink under `root` that packaging would copy. A link in a path that is never copied is not reported."""
    return [
        directory / name
        for directory, dirnames, filenames in walk_packaged(root)
        for name in dirnames + filenames
        if (directory / name).is_symlink()
    ]


def packaged_files(root: Path, suffix: str = "") -> list[Path]:
    """Sorted regular files under `root` that packaging copies and whose name ends with `suffix`. Symlinks are
    left out, because find_symlinks reports them and reading through a link is what the rule exists to prevent."""
    return sorted(
        directory / name
        for directory, _, filenames in walk_packaged(root)
        for name in filenames
        if name.endswith(suffix) and not (directory / name).is_symlink()
    )
