"""Unit tests for the python-project-init script init_project"""
import sys

import pytest

from tests.mocks import REPO_ROOT, load_script

ip = load_script(REPO_ROOT / "skills/python/python-project-init/scripts/init_project.py", "init_project")


def run(dest, *flags):
    """Run main() against `dest` for a project called demo-app"""
    return ip.main([str(dest), "--name", "demo-app", *flags])


def files(dest):
    """Relative paths of every file under `dest`"""
    return {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}


@pytest.mark.parametrize("package", ["class", "src", "tests", "Upper", "_private", "has-dash"])
def test_rejects_bad_package_names(tmp_path, capsys, package):
    with pytest.raises(SystemExit) as exc:
        run(tmp_path / "p", "--package", package)

    assert exc.value.code == 2
    assert "--package" in capsys.readouterr().err


@pytest.mark.parametrize("version", ["3.9", "3.012", "3.", "4.0", "3.x", "2.7", "3.99", "3.15", "3.12\n", " 3.12"])
def test_rejects_bad_python_versions(tmp_path, capsys, version):
    with pytest.raises(SystemExit):
        run(tmp_path / "p", "--python", version)

    assert "--python" in capsys.readouterr().err


@pytest.mark.parametrize("description", ['say "hi"', "back\\slash", "tab\there", "del\x7fchar", "new\nline"])
def test_rejects_descriptions_that_break_toml(tmp_path, capsys, description):
    with pytest.raises(SystemExit):
        run(tmp_path / "p", "--description", description)

    assert "--description" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["demo\n", "Demo", "demo_app", "-demo", "demo-", "demo--app", ""])
def test_rejects_bad_project_names(tmp_path, capsys, name):
    with pytest.raises(SystemExit):
        ip.main([str(tmp_path / "p"), "--name", name])

    assert "--name" in capsys.readouterr().err


@pytest.mark.parametrize("version", ["3.10", "3.12", "3.14"])
def test_accepts_the_supported_python_range(tmp_path, version):
    assert run(tmp_path / "p", "--python", version) == 0


def test_dry_run_writes_nothing(tmp_path, capsys):
    dest = tmp_path / "p"

    assert run(dest) == 0
    assert not dest.exists()
    assert "Dry run: 16 file(s)" in capsys.readouterr().out


def test_apply_creates_app_layout(tmp_path):
    dest = tmp_path / "p"

    assert run(dest, "--apply") == 0
    assert {"pyproject.toml", "Makefile", "AGENTS.md", "scripts/ci.sh", ".github/workflows/ci.yaml",
            "src/__init__.py", "src/example.py", "tests/test_example.py"} <= files(dest)
    assert [p.name for p in (dest / ".github/workflows").iterdir()] == ["ci.yaml"]
    assert (dest / "scripts/ci.sh").stat().st_mode & 0o111


def test_apply_creates_lib_layout(tmp_path):
    dest = tmp_path / "p"

    assert run(dest, "--apply", "--layout", "lib") == 0
    assert {"src/demo_app/__init__.py", "src/demo_app/example.py", "src/demo_app/py.typed"} <= files(dest)
    assert "from demo_app.example import slugify" in (dest / "tests/test_example.py").read_text(encoding="utf-8")
    assert 'packages = ["src/demo_app"]' in (dest / "pyproject.toml").read_text(encoding="utf-8")


def test_generated_pyproject_is_valid_toml(tmp_path):
    tomllib = pytest.importorskip("tomllib")
    dest = tmp_path / "p"
    run(dest, "--apply", "--description", "Demo: a thing", "--python", "3.13", "--line-length", "100")

    data = tomllib.loads((dest / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["project"]["name"] == "demo-app"
    assert data["project"]["requires-python"] == ">=3.13"
    assert data["tool"]["ruff"]["line-length"] == 100
    assert data["tool"]["ruff"]["target-version"] == "py313"


def test_existing_file_is_a_conflict_and_nothing_is_written(tmp_path, capsys):
    dest = tmp_path / "p"
    dest.mkdir()
    (dest / "Makefile").write_text("mine\n", encoding="utf-8")

    assert run(dest, "--apply") == 1
    assert files(dest) == {"Makefile"}
    assert (dest / "Makefile").read_text(encoding="utf-8") == "mine\n"
    assert "conflict Makefile (already exists)" in capsys.readouterr().out


def test_parent_that_is_a_file_is_a_conflict_without_a_traceback(tmp_path, capsys):
    dest = tmp_path / "p"
    dest.mkdir()
    (dest / "src").write_text("a file\n", encoding="utf-8")

    assert run(dest, "--apply") == 1
    assert files(dest) == {"src"}
    assert "conflict src/example.py (src is not a directory)" in capsys.readouterr().out


def test_destination_under_a_file_is_a_conflict(tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")

    assert run(blocker / "p", "--apply") == 1
    assert "is not a directory" in capsys.readouterr().out


def test_destination_that_is_a_file_is_an_error(tmp_path, capsys):
    target = tmp_path / "f"
    target.write_text("x", encoding="utf-8")

    assert run(target) == 1
    assert "not a directory" in capsys.readouterr().err


def test_write_error_is_reported_without_a_traceback(tmp_path, capsys, monkeypatch):
    def boom(*_args, **_kwargs):
        raise PermissionError("disk says no")

    monkeypatch.setattr(ip.Path, "write_bytes", boom)

    assert run(tmp_path / "p", "--apply") == 1
    assert "disk says no" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell script")
def test_ci_script_cleanup_removes_artifacts_and_keeps_source_venv_and_git(tmp_path):
    import subprocess

    dest = tmp_path / "p"
    run(dest, "--apply")
    for rel in ("build", "dist", "src/build", "tests/dist", "src/__pycache__", ".venv/lib/__pycache__", ".git/hooks/__pycache__", "tests/.mypy_cache"):
        (dest / rel).mkdir(parents=True)
        (dest / rel / "f.txt").write_text("x", encoding="utf-8")

    result = subprocess.run(["bash", "scripts/ci.sh", "cleanup"], cwd=dest, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert not (dest / "build").exists() and not (dest / "dist").exists() and not (dest / "src/__pycache__").exists()
    assert (dest / "src/build/f.txt").exists() and (dest / "tests/dist/f.txt").exists()
    assert not (dest / "tests/.mypy_cache").exists()
    assert (dest / ".venv/lib/__pycache__/f.txt").exists() and (dest / ".git/hooks/__pycache__/f.txt").exists()
