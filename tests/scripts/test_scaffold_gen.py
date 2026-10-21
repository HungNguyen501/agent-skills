"""Unit tests for module scaffold_gen"""
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import build
import scaffold_gen
from tests.mocks import REPO_ROOT


def test_the_committed_scripts_match_the_template():
    assert scaffold_gen.stale() == []


@pytest.mark.parametrize("variant", sorted(scaffold_gen.VARIANTS))
def test_rendered_script_is_complete(variant):
    text = scaffold_gen.render(variant)

    assert text.startswith(scaffold_gen.HEADER)
    assert "@@" not in text
    compile(text, variant, "exec")  # valid Python


def test_only_the_claude_script_has_the_claude_extras():
    claude, codex = scaffold_gen.render("claude"), scaffold_gen.render("codex")

    assert "def write_claude_extras" in claude and "write_claude_extras(args.dest)" in claude
    assert "settings.example.json" in claude
    assert "claude" not in codex.lower().replace("claude code", "")
    assert 'EXTRA_FILES = ()' in codex
    assert 'SKILLS_DIR = ".agents/skills"' in codex and 'INSTRUCTIONS = "AGENTS.md"' in codex


def test_fill_keeps_and_drops_blocks_and_replaces_tokens():
    template = "a = '@@X@@'\n# @@IF one\nkept\n# @@END\n@@IF two\ndropped\n@@END\nend\n"

    assert scaffold_gen.fill(template, {"X": "1"}, {"one"}) == "a = '1'\nkept\nend\n"
    assert scaffold_gen.fill(template, {"X": "1"}, {"two"}) == "a = '1'\ndropped\nend\n"
    assert scaffold_gen.fill(template, {"X": "1"}, set()) == "a = '1'\nend\n"


def test_fill_collapses_the_blank_lines_a_dropped_block_leaves():
    template = "one\n\n\n# @@IF x\nblock\n# @@END\n\n\ntwo\n"

    assert scaffold_gen.fill(template, {}, set()) == "one\n\n\ntwo\n"


@pytest.mark.parametrize(
    "template, message",
    [
        ("@@NOPE@@\n", "unknown token @@NOPE@@"),
        ("@@END\n", "@@END without @@IF"),
        ("@@IF x\ntext\n", "ends inside an @@IF block"),
        ("@@IF x\n@@IF y\n@@END\n@@END\n", "blocks do not nest"),
    ],
)
def test_fill_rejects_a_broken_template(template, message):
    with pytest.raises(ValueError, match=message):
        scaffold_gen.fill(template, {}, {"x", "y"})


def test_unknown_variant_is_an_error():
    with pytest.raises(KeyError):
        scaffold_gen.render("nope")


@pytest.fixture(name="root")
def gen_root(tmp_path):
    """A hub-like tree that holds only the template"""
    (tmp_path / scaffold_gen.TEMPLATE).parent.mkdir(parents=True)
    shutil.copy(REPO_ROOT / scaffold_gen.TEMPLATE, tmp_path / scaffold_gen.TEMPLATE)
    return tmp_path


def test_missing_and_edited_scripts_are_stale_and_write_all_repairs_them(root):
    paths = [spec["path"] for spec in scaffold_gen.VARIANTS.values()]
    assert scaffold_gen.stale(root) == paths

    assert scaffold_gen.write_all(root) == paths
    assert scaffold_gen.stale(root) == []

    (root / paths[0]).write_text("hand edited\n", encoding="utf-8")
    assert scaffold_gen.stale(root) == [paths[0]]
    assert scaffold_gen.write_all(root) == [paths[0]]
    assert scaffold_gen.write_all(root) == []  # nothing left to write


def test_build_check_fails_when_a_generated_script_is_stale(capsys):
    stale = [Path("skills/scaffolding/scaffold-agent-repo-cc/scripts/scaffold.py")]

    with patch.object(sys, "argv", ["build.py", "--check"]), patch.object(scaffold_gen, "stale", return_value=stale):
        assert build.main() == 1

    out = capsys.readouterr().out
    assert "stale generated scripts" in out and "scaffold-agent-repo-cc" in out


def test_build_reports_a_broken_template_instead_of_a_traceback(capsys):
    with patch.object(sys, "argv", ["build.py", "--check"]), patch.object(scaffold_gen, "stale", side_effect=ValueError("bad template")):
        assert build.main() == 1

    assert "error: bad template" in capsys.readouterr().out
