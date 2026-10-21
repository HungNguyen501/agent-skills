"""Unit tests for how the scaffold scripts refuse unsafe input and undo a failed install"""
import subprocess

import pytest

from tests.mocks import make_skill, symlink_or_skip
from tests.skills.helpers import VARIANTS, fail_manifest_write, load_variant, manifest


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


@pytest.mark.parametrize(
    "content",
    [
        '{"skills": [null]}',
        '{"skills": [1]}',
        '{"skills": ["../escape"]}',
        '{"skills": ["a/b"]}',
        '{"skills": ["alpha\\n"]}',
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


def test_skill_behind_a_symlinked_domain_folder_is_not_installable(env, tmp_path, capsys):
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


def test_metadata_failure_after_the_swap_restores_the_old_skills(env, monkeypatch):
    module, _, dest, skills_dir, run = env
    run("--skills", "alpha,beta")
    (dest / module.INSTRUCTIONS).unlink()
    for name in ("alpha", "beta"):
        (skills_dir / name / "marker.txt").write_text(f"old {name}\n", encoding="utf-8")
    before = manifest(skills_dir)
    fail_manifest_write(module, monkeypatch)

    with pytest.raises(OSError, match="disk full"):
        run("--skills", "alpha,beta", "--force")

    for name in ("alpha", "beta"):
        assert (skills_dir / name / "marker.txt").read_text(encoding="utf-8") == f"old {name}\n"
    assert sorted(p.name for p in skills_dir.iterdir()) == [".hub-skills.json", "alpha", "beta"]
    assert manifest(skills_dir) == before
    assert not (dest / module.INSTRUCTIONS).exists()


def test_metadata_failure_on_a_fresh_install_leaves_nothing_behind(env, monkeypatch):
    module, _, dest, skills_dir, run = env
    fail_manifest_write(module, monkeypatch)

    with pytest.raises(OSError, match="disk full"):
        run("--skills", "alpha")

    assert list(skills_dir.iterdir()) == []
    assert not (dest / module.INSTRUCTIONS).exists()


def test_force_refuses_a_file_where_a_skill_folder_belongs(env, capsys):
    _, _, _, skills_dir, run = env
    skills_dir.mkdir(parents=True)
    (skills_dir / "alpha").write_text("not a folder\n", encoding="utf-8")

    assert run("--skills", "alpha", "--force") == 1
    assert "not a plain folder" in capsys.readouterr().err
    assert (skills_dir / "alpha").read_text(encoding="utf-8") == "not a folder\n"


def test_force_refuses_a_symlink_where_a_skill_folder_belongs(env, tmp_path, capsys):
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

    fail_manifest_write(module, monkeypatch)
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
    fail_manifest_write(module, monkeypatch)

    with pytest.raises(OSError, match="disk full"):
        run("--skills", "alpha")

    assert gitignore.read_text(encoding="utf-8") == "build/\n"
    assert not (dest / ".claude/settings.example.json").exists()


def test_extra_files_are_removed_on_failure_when_the_run_created_them(env, monkeypatch):
    module, _, dest, _, run = env
    if not module.EXTRA_FILES:
        pytest.skip("this layout writes no extra files")
    fail_manifest_write(module, monkeypatch)

    with pytest.raises(OSError, match="disk full"):
        run("--skills", "alpha")

    assert not (dest / ".gitignore").exists()
    assert not (dest / ".claude/settings.example.json").exists()


@pytest.mark.parametrize("depth", [0, 1])
def test_symlinked_install_ancestors_are_refused(env, tmp_path, capsys, depth):
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
    module, _, dest, _, run = env
    missing = tmp_path / "elsewhere" / "target.md"
    symlink_or_skip(str(missing), dest / module.INSTRUCTIONS)

    assert run("--skills", "alpha") == 0
    assert (dest / module.INSTRUCTIONS).is_symlink()
    assert not missing.exists() and not missing.parent.exists()


def test_a_symlinked_extra_file_is_refused_and_its_target_is_unchanged(env, tmp_path, capsys):
    module, _, dest, skills_dir, run = env
    if not module.EXTRA_FILES:
        pytest.skip("this layout writes no extra files")
    external = tmp_path / "shared-gitignore"
    external.write_text("*.log\n", encoding="utf-8")
    symlink_or_skip(str(external), dest / ".gitignore")

    assert run("--skills", "alpha") == 1
    assert "refusing to write through it" in capsys.readouterr().err
    assert external.read_text(encoding="utf-8") == "*.log\n"
    assert not skills_dir.exists()


def test_a_dangling_extra_file_link_is_refused_and_its_target_is_not_created(env, tmp_path, capsys):
    module, _, dest, _, run = env
    if not module.EXTRA_FILES:
        pytest.skip("this layout writes no extra files")
    missing = tmp_path / "nowhere" / ".gitignore"
    symlink_or_skip(str(missing), dest / ".gitignore")

    assert run("--skills", "alpha") == 1
    assert "refusing to write through it" in capsys.readouterr().err
    assert not missing.parent.exists()


def test_a_dangling_instruction_link_survives_a_failed_install(env, tmp_path, monkeypatch):
    module, _, dest, _, run = env
    missing = tmp_path / "elsewhere" / "target.md"
    symlink_or_skip(str(missing), dest / module.INSTRUCTIONS)
    fail_manifest_write(module, monkeypatch)

    with pytest.raises(OSError, match="disk full"):
        run("--skills", "alpha")

    assert (dest / module.INSTRUCTIONS).is_symlink()
    assert not missing.parent.exists()


def test_an_instruction_folder_is_kept_and_does_not_mask_the_original_failure(env, monkeypatch):
    module, _, dest, _, run = env
    (dest / module.INSTRUCTIONS).mkdir()
    gitignore = dest / ".gitignore"
    gitignore.write_text("build/\n", encoding="utf-8")
    fail_manifest_write(module, monkeypatch)

    with pytest.raises(OSError, match="disk full"):
        run("--skills", "alpha")

    assert (dest / module.INSTRUCTIONS).is_dir()
    assert gitignore.read_text(encoding="utf-8") == "build/\n"


def test_rollback_never_rewrites_an_existing_instruction_file(env, monkeypatch):
    module, _, dest, _, run = env
    path = dest / module.INSTRUCTIONS
    path.write_text("mine\n", encoding="utf-8")
    written = []
    real = module.write_atomic

    def spy(target, content):
        written.append(target.name)
        return real(target, content)

    monkeypatch.setattr(module, "write_atomic", spy)
    fail_manifest_write(module, monkeypatch)

    with pytest.raises(OSError, match="disk full"):
        run("--skills", "alpha")

    assert module.INSTRUCTIONS not in written
    assert path.read_text(encoding="utf-8") == "mine\n"


def test_a_failing_restore_is_reported_and_does_not_hide_the_original_error(env, monkeypatch, capsys):
    module, _, dest, _, run = env
    if not module.EXTRA_FILES:
        pytest.skip("this layout writes no extra files")
    (dest / ".gitignore").write_text("build/\n", encoding="utf-8")
    real = module.write_atomic

    def broken(target, content):
        if target.name == ".gitignore" and content == b"build/\n":
            raise OSError("read-only")
        return real(target, content)

    monkeypatch.setattr(module, "write_atomic", broken)
    fail_manifest_write(module, monkeypatch)

    with pytest.raises(OSError, match="disk full"):
        run("--skills", "alpha")

    assert "could not restore" in capsys.readouterr().err


@pytest.mark.parametrize("flags", [[], ["--dry-run"]])
@pytest.mark.parametrize("dangling", [False, True])
def test_a_manifest_symlink_is_refused_and_left_untouched(env, tmp_path, capsys, flags, dangling):
    _, _, _, skills_dir, run = env
    skills_dir.mkdir(parents=True)
    target = tmp_path / "shared-manifest.json"
    if not dangling:
        target.write_text('{"skills": []}', encoding="utf-8")
    symlink_or_skip(str(target), skills_dir / ".hub-skills.json")

    assert run("--skills", "alpha", *flags) == 1
    assert "refusing to replace it" in capsys.readouterr().err
    assert (skills_dir / ".hub-skills.json").is_symlink()
    assert target.exists() is (not dangling)
    assert not (skills_dir / "alpha").exists()


@pytest.mark.parametrize("flags", [[], ["--dry-run"]])
@pytest.mark.parametrize("depth", [0, 1])
def test_a_file_where_an_install_folder_belongs_is_refused_even_on_a_dry_run(env, capsys, flags, depth):
    module, _, dest, _, run = env
    parts = module.SKILLS_DIR.split("/")
    parent = dest
    for part in parts[:depth]:
        parent = parent / part
        parent.mkdir()
    (parent / parts[depth]).write_text("a file\n", encoding="utf-8")

    assert run("--skills", "alpha", *flags) == 1
    assert "exists and is not a directory" in capsys.readouterr().err


def test_a_folder_at_the_manifest_path_is_a_clean_error_not_a_traceback(env, capsys):
    _, _, _, skills_dir, run = env
    (skills_dir / ".hub-skills.json").mkdir(parents=True)

    assert run("--skills", "alpha") == 1
    assert "cannot be read" in capsys.readouterr().err
    assert not (skills_dir / "alpha").exists()


def _folders(tmp_path):
    """A freshly installed target and the backup of the skill it replaced"""
    target, backup = tmp_path / "target", tmp_path / "backup"
    for folder, content in ((target, "new"), (backup, "old")):
        folder.mkdir()
        (folder / "f.txt").write_text(content, encoding="utf-8")
    return target, backup


def test_roll_back_puts_the_old_skill_back(env, tmp_path):
    module, *_ = env
    target, backup = _folders(tmp_path)

    module.roll_back([(target, backup)])

    assert (target / "f.txt").read_text(encoding="utf-8") == "old"
    assert not backup.exists()


def test_roll_back_keeps_the_backup_and_does_not_raise_when_removal_fails(env, tmp_path, monkeypatch, capsys):
    module, *_ = env
    target, backup = _folders(tmp_path)

    def busy(_path, *_args, **_kwargs):
        raise OSError("busy")

    monkeypatch.setattr(module.shutil, "rmtree", busy)

    module.roll_back([(target, backup)])

    err = capsys.readouterr().err
    assert "could not remove" in err and f"stays at {backup}" in err
    assert (backup / "f.txt").read_text(encoding="utf-8") == "old"


def test_roll_back_reports_a_failed_rename_and_continues_with_the_rest(env, tmp_path, monkeypatch, capsys):
    module, *_ = env
    first, first_backup = _folders(tmp_path)
    second, second_backup = tmp_path / "t2", tmp_path / "b2"
    for folder in (second, second_backup):
        folder.mkdir()
    real_rename = module.Path.rename

    def flaky(self, destination):
        if self == second_backup:
            raise OSError("rename failed")
        return real_rename(self, destination)

    monkeypatch.setattr(module.Path, "rename", flaky)

    module.roll_back([(first, first_backup), (second, second_backup)])

    assert "could not restore" in capsys.readouterr().err
    assert (first / "f.txt").read_text(encoding="utf-8") == "old"
    assert second_backup.exists()


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_hub_revision_gives_up_on_a_hung_git(variant, tmp_path, monkeypatch):
    module = load_variant(variant)
    seen = {}

    def hung(*_args, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired("git", kwargs["timeout"])

    monkeypatch.setattr(module.subprocess, "run", hung)

    assert module.hub_revision(tmp_path) == "unknown"
    assert seen["timeout"] == module.GIT_TIMEOUT_SECONDS


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_hub_revision_is_unknown_when_git_is_missing(variant, tmp_path, monkeypatch):
    module = load_variant(variant)

    def missing(*_args, **_kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(module.subprocess, "run", missing)

    assert module.hub_revision(tmp_path) == "unknown"
