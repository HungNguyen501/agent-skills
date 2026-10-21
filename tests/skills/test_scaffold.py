"""Unit tests for the scaffolding scripts of scaffold-agent-repo-cc and scaffold-agent-repo-codex"""
import json

import pytest

from tests.mocks import REPO_ROOT, load_script, make_skill

VARIANTS = {
    "cc": (".claude/skills", "CLAUDE.md"),
    "codex": (".agents/skills", "AGENTS.md"),
}


@pytest.fixture(name="env", params=sorted(VARIANTS))
def gen_env(request, tmp_path, monkeypatch):
    """(module, hub, dest, skills_dir, run) for one scaffolder variant, with a hub holding skills alpha and beta"""
    variant = request.param
    module = load_script(
        REPO_ROOT / f"skills/scaffolding/scaffold-agent-repo-{variant}/scripts/scaffold.py", f"scaffold_{variant}"
    )
    hub = tmp_path / "hub"
    domain = hub / "skills" / "demo"
    make_skill(domain, "alpha", files={"references/a.md": "alpha\n"})
    make_skill(domain, "beta")
    dest = tmp_path / "dest"
    dest.mkdir()
    monkeypatch.setattr(module, "hub_revision", lambda _hub: "rev1")

    def run(*extra):
        return module.main(["--hub", str(hub), "--dest", str(dest), *extra])

    return module, hub, dest, dest / VARIANTS[variant][0], run


def manifest(skills_dir):
    """The parsed .hub-skills.json"""
    return json.loads((skills_dir / ".hub-skills.json").read_text(encoding="utf-8"))


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


def test_failed_copy_keeps_installed_skill_and_leaves_no_staging(env, monkeypatch):
    module, _, _, skills_dir, run = env
    run("--skills", "alpha")
    (skills_dir / "alpha/marker.txt").write_text("old\n", encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("copy failed")

    monkeypatch.setattr(module.shutil, "copytree", boom)

    with pytest.raises(OSError, match="copy failed"):
        run("--skills", "alpha", "--force")

    assert (skills_dir / "alpha/marker.txt").exists()
    assert sorted(p.name for p in skills_dir.iterdir()) == [".hub-skills.json", "alpha"]


def test_staging_never_touches_a_user_folder_with_the_old_staging_name(env):
    _, _, _, skills_dir, run = env
    keep = skills_dir / ".alpha.new" / "keep.txt"
    keep.parent.mkdir(parents=True)
    keep.write_text("user data\n", encoding="utf-8")

    assert run("--skills", "alpha") == 0
    assert keep.read_text(encoding="utf-8") == "user data\n"


def test_corrupt_manifest_stops_before_any_write(env, capsys):
    _, _, _, skills_dir, run = env
    skills_dir.mkdir(parents=True)
    (skills_dir / ".hub-skills.json").write_text("{not json", encoding="utf-8")

    assert run("--skills", "alpha") == 1
    assert "not valid JSON" in capsys.readouterr().err
    assert not (skills_dir / "alpha").exists()


def test_manifest_without_skills_list_is_rejected(env, capsys):
    _, _, _, skills_dir, run = env
    skills_dir.mkdir(parents=True)
    (skills_dir / ".hub-skills.json").write_text('{"skills": "alpha"}', encoding="utf-8")

    assert run("--skills", "beta") == 1
    assert "not a hub manifest" in capsys.readouterr().err


def test_manifest_records_a_revision_per_skill(env):
    module, _, _, skills_dir, run = env
    run("--skills", "alpha")
    module.hub_revision = lambda _hub: "rev2"
    run("--skills", "beta")

    data = manifest(skills_dir)

    assert data["skills"] == ["alpha", "beta"]
    assert data["revisions"] == {"alpha": "rev1", "beta": "rev2"}
    assert data["hub_revision"] == "rev2"


def test_reinstalling_one_skill_leaves_the_other_revision_alone(env):
    module, _, _, skills_dir, run = env
    run("--skills", "alpha,beta")
    module.hub_revision = lambda _hub: "rev3"
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
    import shutil

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
