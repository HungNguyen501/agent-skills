"""Unit tests for installing skills with the scaffold scripts of scaffold-agent-repo-cc and scaffold-agent-repo-codex"""
import json
import shutil

import pytest

from tests.skills.helpers import manifest


def test_installs_skill_without_evals(env):
    _, _, _, skills_dir, run = env

    assert run("--skills", "alpha") == 0
    assert (skills_dir / "alpha/SKILL.md").exists()
    assert (skills_dir / "alpha/references/a.md").exists()
    assert not (skills_dir / "alpha/evals").exists()


def test_repeated_names_install_once(env):
    _, _, _, skills_dir, run = env

    assert run("--skills", "alpha,alpha, alpha") == 0
    assert (skills_dir / "alpha/SKILL.md").exists()
    assert manifest(skills_dir)["skills"] == ["alpha"]


@pytest.mark.parametrize("value", ["", ",", " , ,"])
def test_empty_skill_list_is_an_error(env, capsys, value):
    _, _, dest, _, run = env

    assert run("--skills", value) == 1
    assert "no skill names" in capsys.readouterr().err
    assert list(dest.iterdir()) == []


def test_unknown_skill_lists_available_names(env, capsys):
    *_, run = env

    assert run("--skills", "nope") == 1
    assert "Available: alpha, beta" in capsys.readouterr().err


def test_existing_skill_needs_force(env, capsys):
    _, _, _, skills_dir, run = env
    run("--skills", "alpha")
    (skills_dir / "alpha/mine.txt").write_text("keep\n", encoding="utf-8")

    assert run("--skills", "alpha") == 1
    assert (skills_dir / "alpha/mine.txt").exists()
    assert "--force" in capsys.readouterr().err

    assert run("--skills", "alpha", "--force") == 0
    assert not (skills_dir / "alpha/mine.txt").exists()


def test_dry_run_writes_nothing(env, capsys):
    _, _, dest, _, run = env

    assert run("--skills", "alpha", "--dry-run") == 0
    assert list(dest.iterdir()) == []
    assert "dry run: nothing written" in capsys.readouterr().out


def test_manifest_records_a_revision_per_skill(env, monkeypatch):
    module, _, _, skills_dir, run = env
    run("--skills", "alpha")
    monkeypatch.setattr(module, "hub_revision", lambda _hub: "rev2")
    run("--skills", "beta")

    data = manifest(skills_dir)

    assert data["skills"] == ["alpha", "beta"]
    assert data["revisions"] == {"alpha": "rev1", "beta": "rev2"}
    assert data["hub_revision"] == "rev2"


def test_reinstalling_one_skill_leaves_the_other_revision_alone(env, monkeypatch):
    module, _, _, skills_dir, run = env
    run("--skills", "alpha,beta")
    monkeypatch.setattr(module, "hub_revision", lambda _hub: "rev3")
    run("--skills", "alpha", "--force")

    assert manifest(skills_dir)["revisions"] == {"alpha": "rev3", "beta": "rev1"}


def test_legacy_manifest_entries_keep_the_old_shared_revision(env):
    _, _, _, skills_dir, run = env
    run("--skills", "alpha")
    legacy = {"skills": ["alpha"], "hub_revision": "old-sha"}
    (skills_dir / ".hub-skills.json").write_text(json.dumps(legacy), encoding="utf-8")

    run("--skills", "beta")

    assert manifest(skills_dir)["revisions"] == {"alpha": "old-sha", "beta": "rev1"}


def test_deleted_skill_folder_is_dropped_from_the_manifest(env):
    _, _, _, skills_dir, run = env
    run("--skills", "alpha,beta")
    shutil.rmtree(skills_dir / "alpha")

    run("--skills", "beta", "--force")

    data = manifest(skills_dir)
    assert data["skills"] == ["beta"]
    assert list(data["revisions"]) == ["beta"]


def test_instruction_file_is_written_once_and_never_overwritten(env):
    module, _, dest, _, run = env
    run("--skills", "alpha")
    path = dest / module.INSTRUCTIONS
    assert "`alpha`" in path.read_text(encoding="utf-8")

    path.write_text("mine\n", encoding="utf-8")
    run("--skills", "beta")

    assert path.read_text(encoding="utf-8") == "mine\n"


def test_instruction_file_is_regenerated_when_an_installed_skill_left_the_hub(env):
    module, hub, dest, _, run = env
    run("--skills", "alpha,beta")
    (dest / module.INSTRUCTIONS).unlink()
    shutil.rmtree(hub / "skills/demo/beta")

    assert run("--skills", "alpha", "--force") == 0
    text = (dest / module.INSTRUCTIONS).read_text(encoding="utf-8")
    assert "`beta`: (not in this hub)" in text and "`alpha`:" in text


def test_old_copies_are_removed_after_a_successful_install(env):
    _, _, _, skills_dir, run = env
    run("--skills", "alpha")
    run("--skills", "alpha", "--force")

    assert sorted(p.name for p in skills_dir.iterdir()) == [".hub-skills.json", "alpha"]
