"""Unit tests for the ansible-project-init script init_project"""
import os
import re
import shutil
import subprocess

import pytest
import yaml

from tests.mocks import REPO_ROOT, load_script

SKILL = REPO_ROOT / "skills/ansible/ansible-project-init"
ip = load_script(SKILL / "scripts/init_project.py", "ansible_init_project")


def run(dest, *flags):
    """Run main() against `dest` for a project called demo-ansible"""
    return ip.main([str(dest), "--name", "demo-ansible", *flags])


def files(dest):
    """Relative paths of every file under `dest`"""
    return {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}


def read(dest, rel):
    """Text of one generated file"""
    return (dest / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["demo\n", "Demo", "demo_ansible", "-demo", "demo-", "demo--app", ""])
def test_rejects_bad_project_names(tmp_path, capsys, name):
    with pytest.raises(SystemExit):
        ip.main([str(tmp_path / "p"), "--name", name])

    assert "--name" in capsys.readouterr().err


@pytest.mark.parametrize("environments", ["staging,staging", "Staging", "stag-ing", "a b", "prod,", "1prod", "stag_ing", "prod\n"])
def test_rejects_bad_environments(tmp_path, capsys, environments):
    with pytest.raises(SystemExit):
        run(tmp_path / "p", "--environments", environments)

    assert "--environments" in capsys.readouterr().err


@pytest.mark.parametrize("version", ["3.10", "3.9", "3.015", "4.0", "3.x", "3.12\n", "3.15"])
def test_rejects_bad_python_versions(tmp_path, capsys, version):
    with pytest.raises(SystemExit):
        run(tmp_path / "p", "--python", version)

    assert "--python" in capsys.readouterr().err


@pytest.mark.parametrize("description", ['say "hi"', "back\\slash", "tab\there", "new\nline"])
def test_rejects_descriptions_that_break_toml(tmp_path, capsys, description):
    with pytest.raises(SystemExit):
        run(tmp_path / "p", "--description", description)

    assert "--description" in capsys.readouterr().err


def test_dry_run_writes_nothing(tmp_path, capsys):
    dest = tmp_path / "p"

    assert run(dest) == 0
    assert not dest.exists()
    expected = len(ip.PROJECT_FILES) + 2 * len(ip.ENV_FILES)
    assert f"Dry run: {expected} file(s)" in capsys.readouterr().out


def test_apply_creates_the_standard_layout(tmp_path):
    dest = tmp_path / "p"

    assert run(dest, "--apply") == 0
    assert {
        "ansible.cfg", "pyproject.toml", "requirements.yml", "Makefile", ".ansible-lint", ".yamllint", ".pre-commit-config.yaml",
        "AGENTS.md", "README.md", "playbooks/site.yml", "playbooks/base.yml",
        "roles/base/meta/argument_specs.yml", "roles/base/molecule/default/molecule.yml",
        "inventories/staging/hosts.yml", "inventories/production/group_vars/all/vault.example.yml",
        ".github/workflows/ci.yaml", ".github/workflows/ansible-check.yaml", ".github/workflows/ansible-apply.yaml",
    } <= files(dest)
    assert not any(p.endswith("vault.yml") for p in files(dest)), "a real vault.yml must never be generated"
    for script in ("run-playbook.sh", "vault-init.sh", "check-vault-encrypted.sh"):
        assert (dest / "scripts" / script).stat().st_mode & 0o111


def test_no_template_token_survives(tmp_path):
    dest = tmp_path / "p"
    run(dest, "--apply", "--connection", "ssm")

    assert [rel for rel in files(dest) if "@@" in read(dest, rel)] == []


@pytest.mark.parametrize("connection", ["ssh", "ssm"])
def test_generated_yaml_parses(tmp_path, connection):
    dest = tmp_path / "p"
    run(dest, "--apply", "--connection", connection)

    for rel in sorted(files(dest)):
        if rel.endswith((".yml", ".yaml")):
            yaml.safe_load(read(dest, rel))


def test_environments_drive_inventories_makefile_and_workflows(tmp_path):
    dest = tmp_path / "p"

    assert run(dest, "--apply", "--environments", "dev,qa,prod") == 0
    assert {f"inventories/{e}/hosts.yml" for e in ("dev", "qa", "prod")} <= files(dest)
    assert not (dest / "inventories/staging").exists()
    assert "ENVIRONMENTS := dev qa prod" in read(dest, "Makefile")
    assert "PROTECTED_ENVS := prod" in read(dest, "Makefile")
    assert 'options: ["dev", "qa", "prod"]' in read(dest, ".github/workflows/ansible-check.yaml")


@pytest.mark.parametrize("workflow", ["ansible-check.yaml", "ansible-apply.yaml"])
def test_yaml_special_environment_names_stay_strings_in_workflow_options(tmp_path, workflow):
    dest = tmp_path / "p"
    run(dest, "--apply", "--environments", "true,null,yes,staging")

    parsed = yaml.safe_load(read(dest, f".github/workflows/{workflow}"))
    options = parsed[True]["workflow_dispatch"]["inputs"]["environment"]["options"]  # PyYAML reads the key `on` as True
    assert options == ["true", "null", "yes", "staging"]


def test_only_production_like_names_are_protected_by_default(tmp_path):
    dest = tmp_path / "p"
    run(dest, "--apply", "--environments", "dev,staging")

    assert "\nPROTECTED_ENVS :=\n" in read(dest, "Makefile")


def test_protected_flag_overrides_the_default(tmp_path, capsys):
    dest = tmp_path / "p"

    assert run(dest, "--apply", "--environments", "dev,live", "--protected", "live") == 0
    assert "PROTECTED_ENVS := live" in read(dest, "Makefile")
    assert "Protected environments (deploy needs CONFIRM): live" in capsys.readouterr().out


def test_protected_flag_rejects_unknown_environments(tmp_path, capsys):
    with pytest.raises(SystemExit):
        run(tmp_path / "p", "--protected", "prd")

    assert "--protected" in capsys.readouterr().err


def test_protected_flag_can_be_empty(tmp_path):
    dest = tmp_path / "p"
    run(dest, "--apply", "--environments", "prod", "--protected", "")

    assert "\nPROTECTED_ENVS :=\n" in read(dest, "Makefile")


def test_ssh_connection_has_no_oidc(tmp_path):
    dest = tmp_path / "p"
    run(dest, "--apply")

    check = read(dest, ".github/workflows/ansible-check.yaml")
    assert "id-token" not in check
    assert "ANSIBLE_SSH_PRIVATE_KEY" in check
    assert "community.aws" not in read(dest, "requirements.yml")
    assert "boto3" not in read(dest, "pyproject.toml")


def test_ssm_connection_uses_oidc_and_aws_collections(tmp_path):
    dest = tmp_path / "p"
    run(dest, "--apply", "--connection", "ssm")

    for workflow in ("ansible-check.yaml", "ansible-apply.yaml"):
        text = read(dest, f".github/workflows/{workflow}")
        assert "      id-token: write\n" in text
        assert "aws-actions/configure-aws-credentials@" in text
        assert "ANSIBLE_SSH_PRIVATE_KEY" not in text
    assert "ansible_connection: community.aws.aws_ssm" in read(dest, "inventories/staging/group_vars/all/connection.yml")
    assert "community.aws" in read(dest, "requirements.yml")
    assert '"boto3"' in read(dest, "pyproject.toml")


def test_workflows_pin_actions_to_commit_shas(tmp_path):
    dest = tmp_path / "p"
    run(dest, "--apply", "--connection", "ssm")

    for rel in sorted(files(dest)):
        if rel.startswith(".github/") and rel.endswith(".yaml"):
            for line in read(dest, rel).splitlines():
                if "uses:" in line and "./.github" not in line:
                    ref = line.split("@", 1)[1].split()[0]
                    assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{rel}: {line.strip()}"


def test_workflows_never_interpolate_inputs_into_scripts(tmp_path):
    dest = tmp_path / "p"
    run(dest, "--apply")

    for workflow in ("ansible-check.yaml", "ansible-apply.yaml"):
        steps = yaml.safe_load(read(dest, f".github/workflows/{workflow}"))["jobs"]
        for job in steps.values():
            for step in job["steps"]:
                assert "inputs." not in step.get("run", ""), f"{workflow}: {step['name']}"


def test_check_and_apply_share_the_run_name_shape(tmp_path):
    dest = tmp_path / "p"
    run(dest, "--apply")

    check = yaml.safe_load(read(dest, ".github/workflows/ansible-check.yaml"))["run-name"]
    apply = yaml.safe_load(read(dest, ".github/workflows/ansible-apply.yaml"))["run-name"]
    assert check.removeprefix("Check ") == apply.removeprefix("Apply ")


def test_apply_workflow_rejects_stale_check_runs(tmp_path):
    dest = tmp_path / "p"
    run(dest, "--apply")

    assert "createdAt" in read(dest, ".github/workflows/ansible-apply.yaml")


def test_ssm_plugin_is_pinned_and_verified(tmp_path):
    dest = tmp_path / "p"
    run(dest, "--apply", "--connection", "ssm")

    text = read(dest, ".github/workflows/ansible-check.yaml")
    assert "/plugin/latest/" not in text
    assert "sha256sum -c" in text


def test_makefile_passes_inputs_through_the_environment(tmp_path):
    dest = tmp_path / "p"
    run(dest, "--apply")

    makefile = read(dest, "Makefile")
    assert "export PLAYBOOK LIMIT TAGS SKIP_TAGS" in makefile
    assert "LIMIT='$(LIMIT)'" not in makefile


@pytest.mark.skipif(shutil.which("yamllint") is None, reason="needs yamllint")
@pytest.mark.parametrize("connection", ["ssh", "ssm"])
def test_generated_project_passes_yamllint(tmp_path, connection):
    dest = tmp_path / "p"
    run(dest, "--apply", "--connection", connection)

    result = subprocess.run(["yamllint", "-c", ".yamllint", "."], cwd=dest, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stdout


def test_pyproject_is_valid_toml(tmp_path):
    tomllib = pytest.importorskip("tomllib")
    dest = tmp_path / "p"
    run(dest, "--apply", "--description", "Demo: a thing", "--python", "3.13", "--connection", "ssm")

    data = tomllib.loads(read(dest, "pyproject.toml"))

    assert data["project"]["name"] == "demo-ansible"
    assert data["project"]["requires-python"] == ">=3.13"
    assert "boto3" in data["project"]["dependencies"]
    assert data["tool"]["uv"]["package"] is False


def test_empty_block_token_drops_its_line_and_multiline_token_is_indented(tmp_path):
    template = tmp_path / "t.tmpl"
    template.write_text("a:\n  @@gone@@\n  @@many@@\nb: @@one@@\n", encoding="utf-8")

    out = ip.render(template, {"gone": "", "many": "x: 1\n\ny: 2", "one": "z"}).decode()

    assert out == "a:\n  x: 1\n\n  y: 2\nb: z\n"


def test_unknown_token_aborts(tmp_path):
    template = tmp_path / "t.tmpl"
    template.write_text("value: @@nope@@\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="unknown token"):
        ip.render(template, {})


def test_existing_file_is_a_conflict_and_nothing_is_written(tmp_path, capsys):
    dest = tmp_path / "p"
    dest.mkdir()
    (dest / "ansible.cfg").write_text("mine\n", encoding="utf-8")

    assert run(dest, "--apply") == 1
    assert files(dest) == {"ansible.cfg"}
    assert read(dest, "ansible.cfg") == "mine\n"
    assert "conflict ansible.cfg (already exists)" in capsys.readouterr().out


@pytest.fixture(name="project")
def generated_project(tmp_path):
    """A generated project with a staging inventory"""
    dest = tmp_path / "p"
    run(dest, "--apply", "--environments", "staging")
    return dest


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
class TestRunPlaybookScript:
    """run-playbook.sh must reject unsafe input before it starts ansible-playbook"""

    @staticmethod
    def call(project, **env):
        full = {"PATH": os.environ["PATH"], "HOME": str(project), **env}
        return subprocess.run(["bash", "scripts/run-playbook.sh"], cwd=project, env=full, capture_output=True, text=True, check=False)

    @pytest.mark.parametrize(
        ("env", "message"),
        [
            ({"MODE": "check"}, "ENVIRONMENT is required"),
            ({"ENVIRONMENT": "staging"}, "MODE is required"),
            ({"ENVIRONMENT": "../x", "MODE": "check"}, "ENVIRONMENT must be"),
            ({"ENVIRONMENT": "nope", "MODE": "check"}, "no inventory directory"),
            ({"ENVIRONMENT": "staging", "MODE": "destroy"}, "MODE must be"),
            ({"ENVIRONMENT": "staging", "MODE": "check", "PLAYBOOK": "../etc/x.yml"}, "PLAYBOOK must be"),
            ({"ENVIRONMENT": "staging", "MODE": "check", "PLAYBOOK": "playbooks/a/../../x.yml"}, "PLAYBOOK must be"),
            ({"ENVIRONMENT": "staging", "MODE": "check", "PLAYBOOK": "playbooks/missing.yml"}, "does not exist"),
            ({"ENVIRONMENT": "staging", "MODE": "check", "LIMIT": "web;rm -rf /"}, "LIMIT has characters"),
            ({"ENVIRONMENT": "staging", "MODE": "check", "TAGS": "a b"}, "TAGS must be"),
            ({"ENVIRONMENT": "staging", "MODE": "check", "SKIP_TAGS": "$(id)"}, "SKIP_TAGS must be"),
        ],
    )
    def test_rejects_bad_input(self, project, env, message):
        result = self.call(project, **env)

        assert result.returncode == 1
        assert message in result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
class TestVaultScripts:
    """The vault helpers must refuse plaintext and never overwrite"""

    def test_check_vault_encrypted_accepts_ciphertext_only(self, project, tmp_path):
        good = tmp_path / "good.yml"
        good.write_text("$ANSIBLE_VAULT;1.1;AES256\n3533\n", encoding="utf-8")
        bad = tmp_path / "bad.yml"
        bad.write_text("vault_x: plain\n", encoding="utf-8")
        script = project / "scripts/check-vault-encrypted.sh"

        assert subprocess.run(["bash", str(script), str(good)], capture_output=True, check=False).returncode == 0
        result = subprocess.run(["bash", str(script), str(good), str(bad)], capture_output=True, text=True, check=False)
        assert result.returncode == 1
        assert "bad.yml is not vault-encrypted" in result.stderr

    def test_vault_init_refuses_an_existing_vault_file(self, project):
        (project / "inventories/staging/group_vars/all/vault.yml").write_text("x\n", encoding="utf-8")

        result = subprocess.run(["bash", "scripts/vault-init.sh", "staging"], cwd=project, capture_output=True, text=True, check=False)

        assert result.returncode == 1
        assert "already exists" in result.stderr

    def test_check_vault_encrypted_reports_missing_files(self, project):
        result = subprocess.run(["bash", str(project / "scripts/check-vault-encrypted.sh"), "gone.yml"], capture_output=True, text=True, check=False)

        assert result.returncode == 1
        assert "gone.yml not found" in result.stderr

    def test_vault_init_leaves_no_plaintext_when_encrypt_fails(self, project, tmp_path):
        fake = tmp_path / "bin"
        fake.mkdir()
        (fake / "ansible-vault").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        (fake / "ansible-vault").chmod(0o755)
        env = {"PATH": f"{fake}{os.pathsep}{os.environ['PATH']}", "HOME": str(project)}

        result = subprocess.run(["bash", "scripts/vault-init.sh", "staging"], cwd=project, env=env, capture_output=True, text=True, check=False)

        assert result.returncode != 0
        assert list((project / "inventories/staging/group_vars/all").glob(".vault.*")) == []
        assert not (project / "inventories/staging/group_vars/all/vault.yml").exists()

    def test_vault_init_rejects_an_unknown_environment(self, project):
        result = subprocess.run(["bash", "scripts/vault-init.sh", "nope"], cwd=project, capture_output=True, text=True, check=False)

        assert result.returncode == 1
        assert "no inventory directory" in result.stderr
