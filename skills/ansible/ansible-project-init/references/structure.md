# Ansible project structure reference

## Contents
- Sources
- Layout decisions
- Pipeline decisions
- Taken from the team's production repo
- Not copied from the production repo
- Left out on purpose
- Extending the starter

Read this when the user asks why the starter looks the way it does, wants a different shape (monorepo, collection, AAP-driven), or asks to change a generated default.

## Sources

- Red Hat Communities of Practice, [automation good practices](https://github.com/redhat-cop/automation-good-practices): structures (landscape, type, function, component), roles, playbooks, inventories, coding style, security, testing, CI/CD and promotion.
- Leo Gallego's [claude-ansible-skills](https://github.com/leogallego/claude-ansible-skills): CoP review and scaffolding skills for roles, collections, execution environments and Molecule. Plugin-per-skill packaging; this hub uses plugin-per-domain instead.
- The Ansible community proposal for an [AI collaboration repo](https://forum.ansible.com/t/proposal-new-repo-for-ansible-ai-collaboration/45575): skills stay tool-agnostic, optional and quick to change.
- The Red Hat Demo Platform [skills marketplace](https://github.com/rhpds/rhdp-skills-marketplace): one plugin per namespace with `.claude-plugin/plugin.json`, a root `marketplace.json`, namespaced invocation (`/plugin:skill`). The hub's `scripts/build.py` produces the same shape per domain.
- The team's production Ansible repo (SSM-connected hosts, vault per environment, check-then-apply deploys).

## Layout decisions

| Choice | Why |
|---|---|
| `inventories/<env>/` with `hosts.yml`, `group_vars/all/`, one directory per environment | CoP: inventory as a directory. Nothing shared between environments, so a change to one cannot reach another. |
| `vars.yml` beside an encrypted `vault.yml`, `vault.example.yml` committed | Reviewers see what a secret feeds without decrypting. The example file gives the shape and the init command encrypts it. |
| `connection.yml` separate from `vars.yml` | The way hosts are reached changes on its own schedule and per environment. |
| `playbooks/site.yml` importing type playbooks, one playbook per type | CoP: no numbered playbooks, no call-order notes. |
| Roles named with underscores, `defaults/` public, `vars/` internal with `__role_` prefix, `argument_specs` | CoP roles chapter. ansible-lint `role-name` rejects hyphens. |
| Example role `base` with a Molecule scenario | A working shape to copy: it passes lint, has validation, a README and an idempotence-checked test. |
| `.ansible-lint` and `.yamllint` at the root | Tools and editors find them without flags. |
| No `inventory =` in `ansible.cfg` | A forgotten `-i` fails instead of hitting another environment. |
| `scripts/run-playbook.sh` as the single run entry point | Make and CI validate environment, playbook path, limit and tags in one place. Inputs arrive as environment variables, never interpolated into a shell. |

## Pipeline decisions

- `ci.yaml`: pre-commit (the same hooks as local), syntax check, gitleaks scan of the full history, and Molecule. Actions pinned to SHAs, `permissions: contents: read`, concurrency per ref.
- `ansible-check.yaml`: `--check --diff` only, the diff goes to the job summary and an artifact.
- `ansible-apply.yaml`: verifies a typed `apply-<env>`, then that the named check run succeeded, ran on the same commit and had the same inputs (compared through `run-name`), before it touches a host.
- One concurrency group per environment so a check and an apply never overlap.
- The vault password is written to a `0600` file and removed in an `if: always()` step. Cloud access uses OIDC, never stored keys.
- GitHub environments carry the secrets. Required reviewers on an environment need a plan that supports them; without that, branch protection on the default branch is the control, and the README says so.

## Taken from the team's production repo

- Per-environment vault password files at `~/.vault/<project>_<env>`.
- `Makefile` as the command surface with `ENV` validated before anything runs.
- Check, then apply, with a typed confirmation.
- SSM connection variables and the OIDC role flow.
- SOC 2 style boundaries in `AGENTS.md`: ask before touching production, never decrypt or print secrets, no live runs unless asked.

## Not copied from the production repo

These show up there and are mistakes or gaps, found in review:

- `inventory = hosts` in `ansible.cfg` pointing at a path that does not exist. Replaced by no default inventory.
- `skip_list` entries for `fqcn`, `role-name` and `var-naming`, and a `warn_list` that downgrades more rules. The starter has an empty `skip_list` and fixes the code.
- `yamllint` with most rules disabled (line length, document start, comments, trailing spaces, final newline) and a `make format` target that rewrites files with `sed` to compensate. The starter keeps the rules and uses pre-commit hooks for whitespace.
- A README that links workflow files that do not exist (`ansible-check.yml`, `ansible-apply.yml`).
- A `latest` image tag default and `shell` for `docker compose up` in the compose role. Prefer `community.docker.docker_compose_v2` and pinned tags.
- Playbooks and roles differing in extension (`.yml` and `.yaml`). The starter uses `.yml` for Ansible content and `.yaml` for GitHub files, which GitHub accepts.

## Left out on purpose

Add per project when needed: dependabot or renovate, CODEOWNERS for `inventories/production/`, a SECURITY policy, execution environments (`ansible-builder`), AAP configuration as code, a collection layout, a release workflow, Slack or ticket notifications on deploy, and a molecule matrix per distribution.

## Extending the starter

- A host type: `playbooks/<type>.yml` that lists roles, imported from `site.yml`, plus a group in each `hosts.yml`.
- A role: copy `roles/base`, rename every `base_` prefix, update `argument_specs`, README and the Molecule `converge.yml`.
- A dynamic inventory: add the plugin config file beside `hosts.yml`, for example `aws_ec2.yml`, and group by tag.
- An environment: copy `inventories/<env>/`, add the name to `ENVIRONMENTS` in the `Makefile` and to the workflow `options`.
