"""Unit tests for module skillpkg"""
import pytest

from skillpkg import PACKAGE_IGNORE, find_symlinks, ignore_patterns
from tests.mocks import make_skill, symlink_or_skip


@pytest.fixture(name="outside")
def gen_outside_file(tmp_path):
    """A file outside every skill, for links to point at"""
    target = tmp_path / "outside.txt"
    target.write_text("x", encoding="utf-8")
    return target


@pytest.mark.parametrize(
    "test_input, expected",
    [
        ("references/link.md", True),
        ("link.md", True),
        ("evals/link.json", False),
        ("__pycache__/x.pyc", False),
        ("references/evals/link.json", False),
        ("references/__pycache__", False),  # a file link that is named like an ignored name
    ],
)
def test_find_symlinks(test_input, expected, tmp_path, outside):
    """Only links in paths that packaging copies are reported"""
    skill = make_skill(tmp_path / "skills", "s")
    (skill / test_input).parent.mkdir(parents=True, exist_ok=True)
    symlink_or_skip(str(outside), skill / test_input)
    assert (skill / test_input in find_symlinks(skill)) is expected


def test_find_symlinks_does_not_descend_into_a_symlinked_directory(tmp_path, outside):
    """The directory link is listed, the links inside its target are not"""
    skill = make_skill(tmp_path / "skills", "s")
    real = tmp_path / "real-dir"
    real.mkdir()
    symlink_or_skip(str(outside), real / "inner-link")
    symlink_or_skip(str(real), skill / "linked-dir")
    assert find_symlinks(skill) == [skill / "linked-dir"]


def test_find_symlinks_without_links_or_root(tmp_path):
    """A tree without symlinks and a missing root both report nothing"""
    skill = make_skill(tmp_path / "skills", "s", files={"references/a.md": "x"})
    assert find_symlinks(skill) == []
    assert find_symlinks(tmp_path / "does-not-exist") == []


def test_ignore_patterns():
    """Exactly the names in PACKAGE_IGNORE are skipped"""
    names = ["SKILL.md", "evals", "__pycache__", "references", "tags", ".git"]
    assert ignore_patterns()("anywhere", names) == set(PACKAGE_IGNORE)
