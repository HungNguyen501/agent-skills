"""Module implements mock objects and builders shared by the tests"""
from pathlib import Path
import json

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GOOD_EVALS = [{"id": str(i), "query": "q", "expected_behavior": ["b"]} for i in range(3)]
DEEPLY_NESTED = "[" * 2000 + "]" * 2000  # makes yaml.safe_load raise RecursionError (about 0.5 s, so use it sparingly)
DEEPLY_NESTED_JSON = "[" * 100_000 + "]" * 100_000  # makes json.loads raise RecursionError; depth 5000 still parses


def make_skill(base: Path, name: str, frontmatter: str | None = None, body: str = "Body.\n", evals=GOOD_EVALS, files=None) -> Path:
    """Create <base>/<name>/SKILL.md (plus evals and any extra files) and return the skill directory"""
    skill = base / name
    skill.mkdir(parents=True)
    front = frontmatter if frontmatter is not None else f"name: {name}\ndescription: Does a thing. Use when testing.\n"
    (skill / "SKILL.md").write_text(f"---\n{front}---\n{body}", encoding="utf-8")
    if evals is not None:
        (skill / "evals").mkdir()
        (skill / "evals" / "evals.json").write_text(json.dumps(evals), encoding="utf-8")
    for rel, content in (files or {}).items():
        path = skill / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return skill


def fm(name: str, extra: str = "") -> str:
    """Frontmatter for a skill called `name`, plus any extra YAML lines such as a metadata block"""
    return f"name: {name}\ndescription: Use when testing.\n{extra}"


def symlink_or_skip(target: str, link: Path) -> None:
    """Create a symlink, skipping the test on platforms that do not allow it"""
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create symlinks here: {exc}")


def add_symlink_loops(skill_dir: Path) -> None:
    """Add a self-referential link and a mutually recursive pair, which make Path.resolve() raise on Python 3.11/3.12"""
    refs = skill_dir / "references"
    refs.mkdir(exist_ok=True)
    symlink_or_skip("loop.md", refs / "loop.md")
    symlink_or_skip("b.md", refs / "a.md")
    symlink_or_skip("a.md", refs / "b.md")
