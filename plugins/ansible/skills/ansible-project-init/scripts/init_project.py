#!/usr/bin/env python3
"""Creates a new Ansible project from the bundled templates.

Usage: init_project.py DEST --name NAME [options] [--apply]

Without --apply it prints the plan and writes nothing. It never overwrites: if any
target file already exists it reports every conflict, writes nothing and exits 1.
Standard library only (Python 3.9+).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "project"

# A token alone on its line may expand to several lines (indented to match) or to nothing (the line is dropped).
BLOCK_RE = re.compile(r"^(?P<indent>[ \t]*)@@(?P<key>\w+)@@[ \t]*$")
TOKEN_RE = re.compile(r"@@(\w+)@@")
NAME_RE = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")  # used with fullmatch
# Environment names become inventory directories, GitHub environments and vault password file names: lowercase letters and digits only.
ENV_RE = re.compile(r"[a-z][a-z0-9]*")
PYTHON_RE = re.compile(r"3\.([1-9][0-9]?)")
# ansible-core 2.18 needs Python 3.11 on the controller. 3.14 is the newest release the generated CI was written against.
MIN_MINOR, MAX_MINOR = 11, 14
CONNECTIONS = ("ssh", "ssm")
# Names that suggest live traffic. They are protected unless --protected says otherwise.
DEFAULT_PROTECTED = ("production", "prod")

# Collections each connection needs. community.docker is for the Molecule docker driver.
COLLECTIONS = {
    "ssh": ["ansible.posix", "community.general", "community.docker"],
    "ssm": ["ansible.posix", "community.general", "community.docker", "community.aws", "amazon.aws"],
}

# (asset, destination) of every file written once per project.
PROJECT_FILES = [
    ("ansible.cfg.tmpl", "ansible.cfg"),
    ("pyproject.toml.tmpl", "pyproject.toml"),
    ("requirements.yml.tmpl", "requirements.yml"),
    ("Makefile.tmpl", "Makefile"),
    ("gitignore.tmpl", ".gitignore"),
    ("configs/ansible-lint.tmpl", ".ansible-lint"),
    ("configs/yamllint.tmpl", ".yamllint"),
    ("configs/pre-commit-config.yaml.tmpl", ".pre-commit-config.yaml"),
    ("README.md.tmpl", "README.md"),
    ("AGENTS.md.tmpl", "AGENTS.md"),
    ("scripts/check-vault-encrypted.sh.tmpl", "scripts/check-vault-encrypted.sh"),
    ("scripts/vault-init.sh.tmpl", "scripts/vault-init.sh"),
    ("scripts/run-playbook.sh.tmpl", "scripts/run-playbook.sh"),
    ("playbooks/site.yml.tmpl", "playbooks/site.yml"),
    ("playbooks/base.yml.tmpl", "playbooks/base.yml"),
    ("role/README.md.tmpl", "roles/base/README.md"),
    ("role/defaults.yml.tmpl", "roles/base/defaults/main.yml"),
    ("role/vars.yml.tmpl", "roles/base/vars/main.yml"),
    ("role/tasks-main.yml.tmpl", "roles/base/tasks/main.yml"),
    ("role/tasks-packages.yml.tmpl", "roles/base/tasks/packages.yml"),
    ("role/tasks-motd.yml.tmpl", "roles/base/tasks/motd.yml"),
    ("role/motd.j2.tmpl", "roles/base/templates/motd.j2"),
    ("role/meta-main.yml.tmpl", "roles/base/meta/main.yml"),
    ("role/meta-argument_specs.yml.tmpl", "roles/base/meta/argument_specs.yml"),
    ("role/molecule-molecule.yml.tmpl", "roles/base/molecule/default/molecule.yml"),
    ("role/molecule-converge.yml.tmpl", "roles/base/molecule/default/converge.yml"),
    ("role/molecule-verify.yml.tmpl", "roles/base/molecule/default/verify.yml"),
    ("github/actions/setup-ansible/action.yaml.tmpl", ".github/actions/setup-ansible/action.yaml"),
    ("github/workflows/ci.yaml.tmpl", ".github/workflows/ci.yaml"),
    ("github/workflows/ansible-check.yaml.tmpl", ".github/workflows/ansible-check.yaml"),
    ("github/workflows/ansible-apply.yaml.tmpl", ".github/workflows/ansible-apply.yaml"),
    ("github/pull_request_template.md.tmpl", ".github/pull_request_template.md"),
    ("github/commit_template.md.tmpl", ".github/commit_template.md"),
]

# (asset, destination) per environment, destination relative to inventories/<env>/.
ENV_FILES = [
    ("inventory/hosts.yml.tmpl", "hosts.yml"),
    ("inventory/vars.yml.tmpl", "group_vars/all/vars.yml"),
    ("inventory/connection-@connection@.yml.tmpl", "group_vars/all/connection.yml"),
    ("inventory/vault.example.yml.tmpl", "group_vars/all/vault.example.yml"),
]

# The commented example host under `base:` in hosts.yml. The group keeps `hosts: {}` so the file stays valid with no hosts.
HOST_EXAMPLES = {
    "ssh": "web01.example.com: {}",
    "ssm": "web01: {ansible_aws_ssm_instance_id: i-0123456789abcdef0}",
}


@dataclass
class Action:
    """One file to create."""

    dest: str
    content: bytes
    executable: bool = False


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parses and validates the command line."""
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("dest", type=Path, help="project directory (created if missing)")
    p.add_argument("--name", required=True, help="project name, lowercase with hyphens, e.g. data-platform-ansible")
    p.add_argument("--description", help="one-line description")
    p.add_argument("--environments", default="staging,production", help="comma-separated environment names (default: staging,production)")
    p.add_argument("--protected", help="environments where `make deploy` demands a typed confirmation, comma-separated, empty for none (default: production and prod when present)")
    p.add_argument("--connection", choices=CONNECTIONS, default="ssh", help="how hosts are reached: ssh keys or AWS SSM (default: ssh)")
    p.add_argument("--python", default="3.12", help="minimum Python version of the controller (default: 3.12)")
    p.add_argument("--apply", action="store_true", help="write the files (default: print the plan only)")
    args = p.parse_args(argv)

    if not NAME_RE.fullmatch(args.name):
        p.error(f"--name must be lowercase letters, digits and single hyphens, got {args.name!r}")
    args.environments = [e.strip(" ") for e in args.environments.split(",")]  # spaces only: a newline must stay invalid
    bad = [e for e in args.environments if not ENV_RE.fullmatch(e)]
    if bad:
        p.error(f"--environments must be lowercase letters and digits, got {bad!r}")
    if len(set(args.environments)) != len(args.environments):
        p.error("--environments must not repeat a name")
    if args.protected is None:
        args.protected = [e for e in args.environments if e in DEFAULT_PROTECTED]
    else:
        args.protected = [e.strip(" ") for e in args.protected.split(",") if e.strip(" ")]
        unknown = [e for e in args.protected if e not in args.environments]
        if unknown:
            p.error(f"--protected must name environments from --environments, got {unknown!r}")
    version = PYTHON_RE.fullmatch(args.python)
    if not version or not MIN_MINOR <= int(version.group(1)) <= MAX_MINOR:
        p.error(f"--python must be one of 3.{MIN_MINOR} to 3.{MAX_MINOR}, got {args.python!r}")
    args.description = args.description or f"Ansible automation for {args.name}"
    if re.search(r'["\\\x00-\x1f\x7f]', args.description):
        p.error("--description must not contain quotes, backslashes or control characters (it goes into TOML)")
    return args


def build_structure(name: str, environments: list[str]) -> str:
    """The fenced project tree shown in README.md and AGENTS.md."""
    lines = [
        f"{name}/",
        "├── inventories/<env>/   hosts.yml, group_vars/all/{vars,vault}.yml, one directory per environment",
        "├── playbooks/           site.yml imports one playbook per host type",
        "├── roles/               one role per function, each with a Molecule scenario",
        "├── scripts/             run-playbook.sh, vault-init.sh, check-vault-encrypted.sh",
        "├── .github/             CI, check and apply workflows, PR and commit templates",
        "├── ansible.cfg  requirements.yml  pyproject.toml  Makefile",
        "├── .ansible-lint  .yamllint  .pre-commit-config.yaml",
        "└── AGENTS.md  README.md",
    ]
    return "```text\n" + "\n".join(lines) + "\n```"


def indent_block(text: str, indent: str) -> str:
    """Indents every non-empty line of `text`."""
    return "\n".join(indent + line if line else line for line in text.splitlines())


def build_tokens(args: argparse.Namespace) -> dict[str, str]:
    """Returns the values substituted for @@token@@ in the templates. Per-environment tokens are added by the caller."""
    ssm = args.connection == "ssm"
    envs = args.environments
    protected = [e for e in envs if e in args.protected]
    collections = "\n".join(f"  - name: {c}" for c in COLLECTIONS[args.connection])
    github_rows = (
        "| `AWS_ROLE_ARN` | secret | IAM role the workflows assume through OIDC |\n| `AWS_REGION` | variable | AWS region for API calls |"
        if ssm
        else "| `ANSIBLE_SSH_PRIVATE_KEY` | secret | Private key of the deploy user |\n"
        "| `ANSIBLE_SSH_KNOWN_HOSTS` | secret | `known_hosts` lines of the managed hosts (host key checking stays on) |"
    )
    prereq = (
        "- An AWS profile or role that can start SSM sessions, and the `session-manager-plugin`"
        if ssm
        else "- SSH access to the hosts as the user in `group_vars/all/connection.yml`"
    )
    return {
        "name": args.name,
        "description": args.description,
        "python": args.python,
        "structure": build_structure(args.name, envs),
        "environments_spaced": " ".join(envs),
        "environments_text": ", ".join(f"`{e}`" for e in envs),
        "environments_flow": "[" + ", ".join(envs) + "]",
        "protected_line": " ".join(["PROTECTED_ENVS :=", *protected]),
        "connection_text": "through AWS Systems Manager (SSM), without SSH keys" if ssm else "over SSH",
        "collections": collections,
        # boto3 is what community.aws and amazon.aws import on the controller.
        "python_deps": '    "boto3",\n    "botocore",' if ssm else "",
        "job_permissions": "id-token: write" if ssm else "",
        "prereq_connection": prereq,
        "github_setup_rows": github_rows,
    }


def render(template: Path, tokens: dict[str, str]) -> bytes:
    """Fills the @@token@@ placeholders. An unknown token is a template bug and aborts."""

    def value(key: str) -> str:
        if key not in tokens:
            raise SystemExit(f"error: unknown token @@{key}@@ in {template}")
        return tokens[key]

    out = []
    for line in template.read_text(encoding="utf-8").split("\n"):
        block = BLOCK_RE.match(line)
        if not block:
            out.append(TOKEN_RE.sub(lambda match: value(match[1]), line))
        elif value(block["key"]) != "":
            out.append(indent_block(value(block["key"]), block["indent"]))
    return "\n".join(out).encode("utf-8")


def template_actions(pairs: list[tuple[str, str]], tokens: dict[str, str]) -> list[Action]:
    """Renders (asset path, destination) pairs. Shell scripts become executable."""
    actions = []
    for asset, dest in pairs:
        src = ASSETS / asset
        if not src.is_file():
            raise SystemExit(f"error: missing template {src}")
        actions.append(Action(dest, render(src, tokens), executable=dest.endswith(".sh")))
    return actions


def build_plan(args: argparse.Namespace) -> list[Action]:
    """Returns every file to create."""
    tokens = build_tokens(args)
    auth = ASSETS / "snippets" / f"auth-{args.connection}.yaml.tmpl"
    tokens["auth_steps"] = render(auth, tokens).decode("utf-8").rstrip("\n")
    actions = template_actions(PROJECT_FILES, tokens)
    for env in args.environments:
        env_tokens = {**tokens, "env": env, "host_example": HOST_EXAMPLES[args.connection]}
        files = [(asset.replace("@connection@", args.connection), f"inventories/{env}/{dest}") for asset, dest in ENV_FILES]
        actions += template_actions(files, env_tokens)
    return actions


def conflict_reason(path: Path) -> str | None:
    """Why `path` cannot be created, or None. Catches an existing file or link and a parent that is not a directory."""
    if path.exists() or path.is_symlink():
        return "already exists"
    for parent in path.parents:
        if parent.exists() or parent.is_symlink():
            return None if parent.is_dir() else f"{parent.name} is not a directory"
    return None


def find_conflicts(dest: Path, actions: list[Action]) -> dict[str, str]:
    """Maps each destination path that cannot be created to the reason."""
    paths = [a.dest for a in actions]
    if len(paths) != len(set(paths)):
        dupes = sorted({p for p in paths if paths.count(p) > 1})
        raise SystemExit(f"error: plan writes the same path twice: {', '.join(dupes)}")
    return {a.dest: reason for a in actions if (reason := conflict_reason(dest / a.dest))}


def print_plan(args: argparse.Namespace, dest: Path, actions: list[Action], conflicts: dict[str, str]) -> None:
    """Prints the settings and one line per file."""
    print(f"Project: {args.name}  environments: {','.join(args.environments)}  connection: {args.connection}  python: >={args.python}")
    print(f"Protected environments (deploy needs CONFIRM): {','.join(args.protected) or 'none'}")
    print(f"Destination: {dest}")
    for action in actions:
        reason = conflicts.get(action.dest)
        print(f"  {'conflict' if reason else 'create  '} {action.dest}" + (f" ({reason})" if reason else ""))


def write_actions(dest: Path, actions: list[Action]) -> None:
    """Writes every file. Raises OSError, which can leave a partly written project."""
    for action in actions:
        target = dest / action.dest
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(action.content)
        if action.executable:
            target.chmod(0o755)


def main(argv: list[str]) -> int:
    """Prints the plan and, with --apply and no conflicts, writes the files."""
    args = parse_args(argv)
    dest: Path = args.dest.expanduser().resolve()
    if dest.exists() and not dest.is_dir():
        print(f"error: {dest} exists and is not a directory", file=sys.stderr)
        return 1
    actions = build_plan(args)
    conflicts = find_conflicts(dest, actions)
    print_plan(args, dest, actions, conflicts)
    if conflicts:
        print(f"\n{len(conflicts)} path(s) cannot be created. Nothing written. Pick another directory or remove or merge them by hand.")
        return 1
    if not args.apply:
        print(f"\nDry run: {len(actions)} file(s) would be created. Re-run with --apply to write them.")
        return 0
    try:
        write_actions(dest, actions)
    except OSError as error:
        print(f"error: {error}. The project may be partly written in {dest}.", file=sys.stderr)
        return 1
    print(f"\nCreated {len(actions)} file(s) in {dest}.")
    print("Next: install the hub's ansible skills into the project (SKILL.md, step 4).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
