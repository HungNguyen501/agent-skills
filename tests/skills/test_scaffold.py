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


def test_manifest_with_a_string_for_skills_is_rejected(env, capsys):
    _, _, _, skills_dir, run = env
    skills_dir.mkdir(parents=True)
    (skills_dir / ".hub-skills.json").write_text('{"skills": "alpha"}', encoding="utf-8")

    assert run("--skills", "beta") == 1
    assert "`skills` must be a list" in capsys.readouterr().err


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


@pytest.mark.parametrize(
    "content",
    [
        '{"skills": [null]}',
        '{"skills": [1]}',
        '{"skills": ["../escape"]}',
        '{"skills": ["a/b"]}',
        '{"skills": [".hidden"]}',
        '{"skills": [], "revisions": []}',
        '{"skills": [], "revisions": {"a": 1}}',
        '{"skills": [], "hub_revision": 5}',
        "[]",
        "null",
    ],
)
@pytest.mark.parametrize("flags", [[], ["--dry-run"]])
def test_invalid_manifest_values_stop_before_any_write(env, capsys, content, flags):
    _, _, dest, skills_dir, run = env
    skills_dir.mkdir(parents=True)
    (skills_dir / ".hub-skills.json").write_text(content, encoding="utf-8")

    assert run("--skills", "alpha", *flags) == 1
    assert "error:" in capsys.readouterr().err
    assert sorted(p.name for p in skills_dir.iterdir()) == [".hub-skills.json"]
    assert [p.name for p in dest.iterdir() if p.name != skills_dir.parts[len(dest.parts)]] == []


def test_instruction_file_is_regenerated_when_an_installed_skill_left_the_hub(env):
    import shutil

    module, hub, dest, _, run = env
    run("--skills", "alpha,beta")
    (dest / module.INSTRUCTIONS).unlink()
    shutil.rmtree(hub / "skills/demo/beta")

    assert run("--skills", "alpha", "--force") == 0
    text = (dest / module.INSTRUCTIONS).read_text(encoding="utf-8")
    assert "`beta`: (not in this hub)" in text and "`alpha`:" in text


def test_skill_behind_a_symlinked_domain_folder_is_not_installable(env, tmp_path, capsys):
    from tests.mocks import symlink_or_skip

    _, hub, _, skills_dir, run = env
    outside = tmp_path / "outside"
    make_skill(outside, "evil")
    symlink_or_skip(str(outside), hub / "skills" / "linked")

    assert run("--skills", "evil") == 1
    assert "`evil` not found" in capsys.readouterr().err
    assert not skills_dir.exists()


@pytest.mark.parametrize("fail", ["alpha", "beta"])
def test_failed_swap_restores_every_installed_skill(env, monkeypatch, fail):
    module, _, _, skills_dir, run = env
    run("--skills", "alpha,beta")
    for name in ("alpha", "beta"):
        (skills_dir / name / "marker.txt").write_text(f"old {name}\n", encoding="utf-8")
    before = manifest(skills_dir)
    real_rename = module.Path.rename

    def flaky(self, target):
        if self.name.startswith(f".{fail}-"):  # the staging folder of the skill that must fail
            raise OSError("rename failed")
        return real_rename(self, target)

    monkeypatch.setattr(module.Path, "rename", flaky)

    with pytest.raises(OSError, match="rename failed"):
        run("--skills", "alpha,beta", "--force")

    for name in ("alpha", "beta"):
        assert (skills_dir / name / "marker.txt").read_text(encoding="utf-8") == f"old {name}\n"
    assert sorted(p.name for p in skills_dir.iterdir()) == [".hub-skills.json", "alpha", "beta"]
    assert manifest(skills_dir) == before


def test_failed_swap_on_a_fresh_install_leaves_nothing_behind(env, monkeypatch):
    module, _, dest, skills_dir, run = env
    real_rename = module.Path.rename

    def flaky(self, target):
        if self.name.startswith(".beta-"):
            raise OSError("rename failed")
        return real_rename(self, target)

    monkeypatch.setattr(module.Path, "rename", flaky)

    with pytest.raises(OSError, match="rename failed"):
        run("--skills", "alpha,beta")

    assert list(skills_dir.iterdir()) == []
    assert not (dest / module.INSTRUCTIONS).exists()


def _fail_manifest_write(module, monkeypatch):
    """Make the final, atomic manifest write fail the way a full disk would"""
    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(module.os, "replace", boom)


def test_metadata_failure_after_the_swap_restores_the_old_skills(env, monkeypatch):
    module, _, dest, skills_dir, run = env
    run("--skills", "alpha,beta")
    (dest / module.INSTRUCTIONS).unlink()
    for name in ("alpha", "beta"):
        (skills_dir / name / "marker.txt").write_text(f"old {name}\n", encoding="utf-8")
    before = manifest(skills_dir)
    _fail_manifest_write(module, monkeypatch)

    with pytest.raises(OSError, match="disk full"):
        run("--skills", "alpha,beta", "--force")

    for name in ("alpha", "beta"):
        assert (skills_dir / name / "marker.txt").read_text(encoding="utf-8") == f"old {name}\n"
    assert sorted(p.name for p in skills_dir.iterdir()) == [".hub-skills.json", "alpha", "beta"]
    assert manifest(skills_dir) == before
    assert not (dest / module.INSTRUCTIONS).exists()


def test_metadata_failure_on_a_fresh_install_leaves_nothing_behind(env, monkeypatch):
    module, _, dest, skills_dir, run = env
    _fail_manifest_write(module, monkeypatch)

    with pytest.raises(OSError, match="disk full"):
        run("--skills", "alpha")

    assert list(skills_dir.iterdir()) == []
    assert not (dest / module.INSTRUCTIONS).exists()


def test_old_copies_are_removed_after_a_successful_install(env):
    _, _, _, skills_dir, run = env
    run("--skills", "alpha")
    run("--skills", "alpha", "--force")

    assert sorted(p.name for p in skills_dir.iterdir()) == [".hub-skills.json", "alpha"]


def test_force_refuses_a_file_where_a_skill_folder_belongs(env, capsys):
    _, _, _, skills_dir, run = env
    skills_dir.mkdir(parents=True)
    (skills_dir / "alpha").write_text("not a folder\n", encoding="utf-8")

    assert run("--skills", "alpha", "--force") == 1
    assert "not a plain folder" in capsys.readouterr().err
    assert (skills_dir / "alpha").read_text(encoding="utf-8") == "not a folder\n"


def test_force_refuses_a_symlink_where_a_skill_folder_belongs(env, tmp_path, capsys):
    from tests.mocks import symlink_or_skip

    _, _, _, skills_dir, run = env
    skills_dir.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    symlink_or_skip(str(elsewhere), skills_dir / "alpha")

    assert run("--skills", "alpha", "--force") == 1
    assert "not a plain folder" in capsys.readouterr().err
    assert elsewhere.exists()


def test_a_users_tmp_file_next_to_the_manifest_is_never_touched(env, monkeypatch):
    module, _, _, skills_dir, run = env
    skills_dir.mkdir(parents=True)
    mine = skills_dir / ".hub-skills.json.tmp"
    mine.write_text("user data\n", encoding="utf-8")

    assert run("--skills", "alpha") == 0
    assert mine.read_text(encoding="utf-8") == "user data\n"

    _fail_manifest_write(module, monkeypatch)
    with pytest.raises(OSError, match="disk full"):
        run("--skills", "beta")

    assert mine.read_text(encoding="utf-8") == "user data\n"
    assert sorted(p.name for p in skills_dir.iterdir() if p.name.endswith(".tmp")) == [".hub-skills.json.tmp"]


def test_partial_instruction_write_is_removed_on_failure(env, monkeypatch):
    module, _, dest, skills_dir, run = env

    def half_write(_args, _manifest, instructions):
        instructions.write_text("partial", encoding="utf-8")
        raise OSError("disk full")

    monkeypatch.setattr(module, "write_instructions", half_write)

    with pytest.raises(OSError, match="disk full"):
        run("--skills", "alpha")

    assert not (dest / module.INSTRUCTIONS).exists()
    assert list(skills_dir.iterdir()) == []


def test_extra_files_are_restored_when_the_manifest_write_fails(env, monkeypatch):
    module, _, dest, _, run = env
    if not module.EXTRA_FILES:
        pytest.skip("this layout writes no extra files")
    gitignore = dest / ".gitignore"
    gitignore.write_text("build/\n", encoding="utf-8")
    _fail_manifest_write(module, monkeypatch)

    with pytest.raises(OSError, match="disk full"):
        run("--skills", "alpha")

    assert gitignore.read_text(encoding="utf-8") == "build/\n"
    assert not (dest / ".claude/settings.example.json").exists()


def test_extra_files_are_removed_on_failure_when_the_run_created_them(env, monkeypatch):
    module, _, dest, _, run = env
    if not module.EXTRA_FILES:
        pytest.skip("this layout writes no extra files")
    _fail_manifest_write(module, monkeypatch)

    with pytest.raises(OSError, match="disk full"):
        run("--skills", "alpha")

    assert not (dest / ".gitignore").exists()
    assert not (dest / ".claude/settings.example.json").exists()


@pytest.mark.parametrize("depth", [0, 1])
def test_symlinked_install_ancestors_are_refused(env, tmp_path, capsys, depth):
    from tests.mocks import symlink_or_skip

    module, _, dest, _, run = env
    parts = module.SKILLS_DIR.split("/")
    outside = tmp_path / "outside"
    outside.mkdir()
    parent = dest
    for part in parts[:depth]:
        parent = parent / part
        parent.mkdir()
    symlink_or_skip(str(outside), parent / parts[depth])

    assert run("--skills", "alpha") == 1
    assert "is a symlink; refusing to install through it" in capsys.readouterr().err
    assert list(outside.iterdir()) == []


def test_a_dangling_instruction_link_is_kept_and_not_written_through(env, tmp_path):
    from tests.mocks import symlink_or_skip

    module, _, dest, _, run = env
    missing = tmp_path / "elsewhere" / "target.md"
    symlink_or_skip(str(missing), dest / module.INSTRUCTIONS)

    assert run("--skills", "alpha") == 0
    assert (dest / module.INSTRUCTIONS).is_symlink()
    assert not missing.exists() and not missing.parent.exists()
