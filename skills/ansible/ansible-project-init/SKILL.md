---
name: ansible-project-init
description: Initializes a new Ansible playbook-and-roles repository with uv, ansible-lint (production profile), yamllint, Molecule, pre-commit, per-environment inventories, vault scaffolding, check-then-apply GitHub workflows and AGENTS.md, following Red Hat CoP good practices and the team's production repo, then installs this hub's ansible skills into it. Use when asked to create, bootstrap, scaffold or initialize an Ansible project, infrastructure repo or automation repo. Do NOT use to add a role, playbook or host to an existing repo, or to create an Ansible collection.
metadata:
  always: "false"
---

# Initialize an Ansible project

`scripts/init_project.py` renders the bundled templates into a new directory. The templates encode the Red Hat CoP structure (landscape, type, function, component), the shape of the team's production Ansible repo minus its known mistakes, and a hardened check-then-apply pipeline ([references/structure.md](references/structure.md)).

## Workflow

```
- [ ] 1. Collect inputs
- [ ] 2. Dry run, show the plan
- [ ] 3. Apply
- [ ] 4. Install the hub's ansible skills
- [ ] 5. Verify: make install, lint, syntax
- [ ] 6. Report
```

### 1. Inputs

Ask only for what is missing. Use the default when the user has no preference.

| Input | Flag | Default |
|---|---|---|
| Directory | positional | required |
| Name, lowercase with hyphens | `--name` | required |
| One-line description | `--description` | `Ansible automation for <name>` |
| Environments, comma-separated | `--environments` | `staging,production` |
| How hosts are reached | `--connection ssh\|ssm` | `ssh` |
| Minimum controller Python | `--python` | `3.12` |
| Protected environments | `--protected` | `production,prod` |

- `ssh`: SSH keys from CI secrets, host key checking stays on. `ssm`: AWS Systems Manager through OIDC, no keys and no open ports. Choose `ssm` when the hosts are EC2 instances the team already reaches that way.
- Environment names are lowercase letters and digits. Protected environments (default `production` and `prod`, set with `--protected`, empty for none) make `make deploy` need `CONFIRM=apply-<env>`. Ask whether names such as `live` or `prd` should be protected.
- A collection (a repo others install with `ansible-galaxy`) is a different project. Stop and say so.

### 2. Dry run

```bash
python3 scripts/init_project.py DEST --name NAME [flags]
```

Without `--apply` it prints every file and writes nothing. Show the plan. The script never overwrites: if any target exists it lists the conflicts, writes nothing and exits 1. Offer a different directory or merging by hand. Never delete or overwrite a user's file to get past a conflict.

### 3. Apply

Run the same command with `--apply`. The script does not run `git init`. Run it in `DEST` if the directory is not a repository yet.

### 4. Install the hub's ansible skills

Copy every ansible skill of this hub into `DEST` with the `/scaffold-repo` command (the `scaffold-agent-repo-cc` skill for Claude Code, `scaffold-agent-repo-codex` for Codex):

1. List `skills/ansible/` and take every skill except `ansible-project-init`. Do not hardcode the names, new ansible skills must be included. Add `code-review` from `skills/review/`.
2. Run `/scaffold-repo claude DEST <comma-separated names>`, or `codex` for a Codex user.
3. Run its dry run first, show it, then apply.

Skip this step only if the user does not want agent skills.

### 5. Verify

In `DEST`, in this order, each must pass:

```bash
make install
make lint
make syntax
```

`make test` (Molecule) and `make scan` need a running Docker daemon. Run them when Docker is available and say so when it is not. `make syntax` prints a warning that the host list is empty: the inventories ship with no hosts. When something fails, fix the generated file and say what you changed. Do not add a rule to `.ansible-lint` `skip_list` to pass. Needs `uv` and network access for `make install`.

### 6. Report

List the layout, the verify results, and the next steps for the user:
- Add hosts to `inventories/<env>/hosts.yml` and set the values in `group_vars/all/connection.yml`.
- `make vault-init ENV=<env>` for each environment, then `make vault-edit ENV=<env>`. Store each vault password in a password manager.
- Create one GitHub environment per environment and add the secrets listed in `README.md`.
- Enable branch protection requiring the `Lint` and `Molecule` jobs. Review `.github/workflows/` and re-check the action pins against current releases.
- Commit `uv.lock` (created by `make install`). The workflows run `uv sync --locked`.
- Replace the example `base` role with real roles. Keep its shape.

## What you get

```text
ansible.cfg  requirements.yml  pyproject.toml  Makefile
.ansible-lint  .yamllint  .pre-commit-config.yaml  .gitignore
inventories/<env>/   hosts.yml, group_vars/all/{vars.yml, connection.yml, vault.example.yml}
playbooks/           site.yml (landscape) importing base.yml (type)
roles/base/          example function role: defaults, vars, tasks per component, argument_specs, README, Molecule
scripts/             run-playbook.sh (validated entry point), vault-init.sh, check-vault-encrypted.sh
.github/             ci.yaml, ansible-check.yaml, ansible-apply.yaml, setup-ansible action, PR and commit templates
AGENTS.md  README.md
```

## Gotchas

- Action pins are SHAs copied from known-good releases. Check them against current releases when a project is created and keep them pinned to a commit SHA with the version in a comment.
- The Molecule scenario uses `geerlingguy/docker-*-ansible` images pinned by digest (they publish only `latest`). Refresh the digests when creating a project and on a schedule. It uses `molecule-plugins[docker]`. It runs only with a Docker daemon, so the init script's own tests cannot run it. Run `make test` once after init.
- `ansible-lint` runs the `production` profile. Findings in the generated files are template bugs: fix the template, not the rule.
- `exclude-newer = "7 days"` in `pyproject.toml` refuses packages released in the last week. Remove it only when a fix is needed urgently.
- `ansible.cfg` sets no `inventory`, on purpose. Every command passes `-i inventories/<env>`; the Makefile and workflows do it for you.
- The apply workflow compares the check run's title (`run-name`) with its own inputs. Changing the `run-name` of one workflow without the other breaks apply.
- `.claude/skills/` and `.agents/skills/` hold hub skills, not project code. Do not edit them in the project; rerun `/scaffold-repo` with `--force` for the named skills.
- The manifest pins the hub's current commit. Commit the hub's pending skill changes first, or the pin points to a revision without them.
