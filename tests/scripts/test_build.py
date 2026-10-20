"""Unit tests for module build"""
from unittest.mock import patch
import shutil

import pytest

from build import OUTPUTS, _same, generate, install_outputs
from tests.mocks import REPO_ROOT, symlink_or_skip


@patch(target="skilllib.discover", return_value=[])
def test_generate_without_skills(mock_discover, tmp_path):
    """An empty skill collection still produces every output directory, and two builds compare equal"""
    first, second = tmp_path / "one", tmp_path / "two"
    generate(first)
    generate(second)
    assert mock_discover.called
    for name in OUTPUTS:
        assert (first / name).exists(), name
        assert _same(first / name, second / name), name


def test_generate_matches_the_committed_outputs(tmp_path):
    """The committed plugins/ and .claude-plugin/ are up to date; run scripts/build.py when this fails"""
    generate(tmp_path)
    for name in OUTPUTS:
        assert _same(tmp_path / name, REPO_ROOT / name), f"{name} is stale; run scripts/build.py"


@pytest.fixture(name="fresh_outputs")
def gen_fresh_outputs(tmp_path):
    """A freshly generated tree with one file in each output, in its own directory"""
    fresh = tmp_path / "fresh"
    for name in OUTPUTS:
        (fresh / name).mkdir(parents=True)
        (fresh / name / "new.txt").write_text("new", encoding="utf-8")
    return fresh


@pytest.mark.parametrize("kind", ["live-directory-link", "dangling-link", "file-link", "directory", "file", "missing"])
def test_install_outputs(kind, fresh_outputs, tmp_path):
    """Every state an output root can be in is replaced, and a link is removed as a link"""
    root, precious = tmp_path / "root", tmp_path / "precious"
    root.mkdir()
    precious.mkdir()
    (precious / "keep.txt").write_text("keep", encoding="utf-8")
    (tmp_path / "a-file.txt").write_text("x", encoding="utf-8")
    for name in OUTPUTS:
        target = root / name
        if kind == "live-directory-link":
            symlink_or_skip(str(precious), target)
        elif kind == "dangling-link":
            symlink_or_skip(str(tmp_path / "does-not-exist"), target)
        elif kind == "file-link":
            symlink_or_skip(str(tmp_path / "a-file.txt"), target)
        elif kind == "directory":
            target.mkdir()
            (target / "old.txt").write_text("old", encoding="utf-8")
        elif kind == "file":
            target.write_text("old", encoding="utf-8")
    install_outputs(fresh_outputs, root)
    for name in OUTPUTS:
        assert not (root / name).is_symlink(), name
        assert (root / name / "new.txt").read_text(encoding="utf-8") == "new", name
        assert not (root / name / "old.txt").exists(), name
    assert (precious / "keep.txt").read_text(encoding="utf-8") == "keep"  # the link's target is never touched
    assert (tmp_path / "a-file.txt").is_file()


def test_same_reports_a_symlinked_output_root_so_that_a_rebuild_is_recommended_and_works(fresh_outputs, tmp_path):
    """--check flags a link at an output root, and installing repairs it, which is what the message tells you to do"""
    root, elsewhere = tmp_path / "root", tmp_path / "elsewhere"
    root.mkdir()
    elsewhere.mkdir()
    for name in OUTPUTS:
        (elsewhere / name).mkdir()
        (elsewhere / name / "new.txt").write_text("new", encoding="utf-8")  # identical content behind the link
        symlink_or_skip(str(elsewhere / name), root / name)
        assert not _same(fresh_outputs / name, root / name), name
    install_outputs(fresh_outputs, root)
    for name in OUTPUTS:
        assert not (root / name).is_symlink(), name
        assert (root / name / "new.txt").is_file(), name


@pytest.mark.parametrize("test_input", ["tags", ".git", "CVS"])
def test_same_compares_names_that_dircmp_ignores_by_default(test_input, tmp_path):
    """filecmp.dircmp skips these names unless ignore=[], but packaging copies them, so --check has to compare them"""
    a, b = tmp_path / "a", tmp_path / "b"
    for directory in (a, b):
        directory.mkdir()
        (directory / "SKILL.md").write_text("same", encoding="utf-8")
    (a / test_input).write_text("one", encoding="utf-8")
    (b / test_input).write_text("two", encoding="utf-8")
    assert not _same(a, b), "changed"
    (b / test_input).unlink()
    assert not _same(a, b), "missing"
    (b / test_input).write_text("one", encoding="utf-8")
    assert _same(a, b), "identical"


def test_same_executable_bit_only_difference(tmp_path):
    """Equal content with a different owner executable bit is not the same file"""
    a, b = tmp_path / "a.sh", tmp_path / "b.sh"
    for path in (a, b):
        path.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        path.chmod(0o644)
    assert _same(a, b)
    a.chmod(0o755)
    assert not _same(a, b)
    b.chmod(0o755)
    assert _same(a, b)


@pytest.mark.parametrize(
    "test_input",
    [(0o755, 0o700), (0o645, 0o604)],
    ids=["same-owner-exec", "no-owner-exec"],
)
def test_same_ignores_group_and_other_permission_bits(test_input, tmp_path):
    """Git tracks only the owner executable bit, so other differences must not make --check fail forever"""
    a, b = tmp_path / "a.sh", tmp_path / "b.sh"
    for path in (a, b):
        path.write_text("echo hi\n", encoding="utf-8")
    a.chmod(test_input[0])
    b.chmod(test_input[1])
    assert _same(a, b)


@pytest.mark.parametrize("link_on_left", [False, True], ids=["link-in-committed", "link-in-generated"])
def test_same_file_replaced_by_a_symlink(link_on_left, tmp_path):
    """A link to identical content must not pass, in either argument position"""
    real, plain, link = tmp_path / "real.md", tmp_path / "plain.md", tmp_path / "link.md"
    real.write_text("same", encoding="utf-8")
    plain.write_text("same", encoding="utf-8")
    symlink_or_skip(str(real), link)
    a, b = (link, plain) if link_on_left else (plain, link)
    assert not _same(a, b)


@pytest.mark.parametrize("link_on_left", [False, True], ids=["link-in-committed", "link-in-generated"])
def test_same_directory_replaced_by_a_symlink(link_on_left, tmp_path):
    """A link to a directory with identical content must not pass, in either argument position"""
    real, plain, link = tmp_path / "real", tmp_path / "plain", tmp_path / "link"
    for directory in (real, plain):
        directory.mkdir()
        (directory / "SKILL.md").write_text("same", encoding="utf-8")
    symlink_or_skip(str(real), link)
    a, b = (link, plain) if link_on_left else (plain, link)
    assert not _same(a, b)


def test_same_symlink_nested_in_a_compared_tree(tmp_path):
    """A file or a directory swapped for a link deep inside the tree is found, and a broken link is a difference too"""
    trees = {}
    for label in ("a", "b"):
        root = tmp_path / label
        (root / "refs" / "sub").mkdir(parents=True)
        (root / "refs" / "note.md").write_text("same", encoding="utf-8")
        (root / "refs" / "sub" / "deep.md").write_text("same", encoding="utf-8")
        trees[label] = root
    assert _same(trees["a"], trees["b"])

    (trees["b"] / "refs" / "note.md").unlink()
    symlink_or_skip(str(trees["a"] / "refs" / "note.md"), trees["b"] / "refs" / "note.md")
    assert not _same(trees["a"], trees["b"]), "file replaced by a link"

    (trees["b"] / "refs" / "note.md").unlink()
    (trees["b"] / "refs" / "note.md").write_text("same", encoding="utf-8")
    shutil.rmtree(trees["b"] / "refs" / "sub")
    symlink_or_skip(str(trees["a"] / "refs" / "sub"), trees["b"] / "refs" / "sub")
    assert not _same(trees["a"], trees["b"]), "directory replaced by a link"

    (trees["b"] / "refs" / "sub").unlink()
    symlink_or_skip(str(tmp_path / "does-not-exist"), trees["b"] / "refs" / "sub")
    assert not _same(trees["a"], trees["b"]), "directory replaced by a broken link"


def test_same_executable_bit_in_nested_files(tmp_path):
    """The executable bit is compared for files inside compared directories too"""
    da, db = tmp_path / "da", tmp_path / "db"
    for directory in (da, db):
        (directory / "scripts").mkdir(parents=True)
        (directory / "scripts" / "run.py").write_text("print(1)\n", encoding="utf-8")
        (directory / "scripts" / "run.py").chmod(0o644)
    assert _same(da, db)
    (da / "scripts" / "run.py").chmod(0o755)
    assert not _same(da, db)
