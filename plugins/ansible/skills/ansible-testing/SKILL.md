---
name: ansible-testing
description: Testing and quality gates for Ansible content - ansible-lint production profile, yamllint, syntax check, Molecule scenarios with idempotence checks, check-mode correctness, pre-commit and CI parity. Use when setting up linting or CI for an Ansible repo, writing a Molecule scenario, debugging lint or --check failures, or deciding what to test. Do NOT use for running a deploy (ansible-safe-deploys) or style rules (ansible-code-style).
metadata:
  always: "false"
---

# Ansible testing

Source: Red Hat CoP [automation good practices](https://github.com/redhat-cop/automation-good-practices) (testing, CI/CD) and the ansible-lint and Molecule docs.

## Test pyramid for a playbook repo

| Layer | Tool | Catches | Runs |
|---|---|---|---|
| Lint | `yamllint`, `ansible-lint` (profile `production`) | Style, deprecated syntax, unsafe patterns | pre-commit and CI, seconds |
| Syntax | `ansible-playbook --syntax-check -i inventories/<env> playbooks/site.yml` | Broken YAML, unknown keywords, missing roles | CI, seconds |
| Role test | Molecule: converge, idempotence, verify | Role behavior on real containers | CI, minutes |
| Check mode | `--check --diff` against staging | What a change would do to real hosts | before every apply |

Shift left: a finding should surface in the editor or pre-commit, not in a deploy.

## ansible-lint

```yaml
# .ansible-lint
profile: production
exclude_paths:
  - .ansible/
  - .github/
  - "inventories/*/group_vars/**/vault.yml"   # ciphertext
```

- Use `profile: production`, the strictest. Raise findings to errors; do not run with `--offline` unless the network is truly absent.
- A rule in `skip_list` or `warn_list` needs a one-line reason beside it. "Existing code violates it" is a ticket, not a reason.
- Fix findings with `ansible-lint --fix` for the auto-fixable ones, then review the diff.
- Pin the `ansible-lint` and `ansible-core` versions through the lock file so a new release does not fail unrelated pull requests.

## yamllint

Extend `default`. Set indentation to 2 spaces with `indent-sequences: true`, keep `truthy` allowed values `["true", "false"]`, raise `line-length` rather than disabling it (Jinja2 lines run long: 160 as a warning), and require a final newline. Do not disable `trailing-spaces` or `new-line-at-end-of-file`: formatting fixes belong in the editor.

## Molecule

Test each role that has logic. Scenarios live in `roles/<role>/molecule/<scenario>/`.

```yaml
# molecule.yml (docker driver)
driver:
  name: docker
platforms:
  - name: debian12
    image: geerlingguy/docker-debian12-ansible
    pre_build_image: true
    privileged: true
    command: ""
provisioner:
  name: ansible
```

- Sequence: `create`, `converge`, `idempotence`, `verify`, `destroy`. Idempotence fails the run if a second converge reports any change. This is the most valuable check.
- One platform per supported distribution family. A role that claims Debian and RHEL support is tested on both.
- `verify.yml` asserts outcomes (package installed, file mode, service enabled, port open), not that the tasks ran.
- Use systemd-capable images only for roles that manage services; plain images are faster.
- Run `molecule test` per role in CI as a matrix job, so one failing role does not hide others.
- Test names say the expected behavior ("Assert nginx config is valid"), not the implementation.

## Check mode

A role or playbook must work under `--check --diff`, because that is the production dry run.
- Read-only probes (`command` that registers a value) need `check_mode: false` so later tasks have data.
- A task that depends on an earlier real change (install, then configure) can fail in check mode. Guard with `when: not ansible_check_mode` only where unavoidable, and note why.
- Do not mark tasks `check_mode: false` to make a dry run pass if they change the system.

## Parity: pre-commit and CI

- The same commands run in pre-commit and in CI (`make lint`, `make syntax`). Developers cannot pass locally and fail in CI.
- Pre-commit holds fast checks only (lint, secret scan, vault-encrypted check). Molecule runs in CI.
- Pin GitHub Actions to commit SHAs with the version in a comment, and `permissions: contents: read`.
- Make the lint job a required status check in branch protection.

## Gotchas

- `ansible-lint` fails on a role named with hyphens (`role-name`). Rename the role rather than skipping the rule.
- Lint finds collection modules only when the collections are installed. Install `requirements.yml` first, in CI too.
- Molecule `converge` using `ansible.builtin.include_role` skips role argument validation unless the role is called with its real variables.
- Idempotence failures are usually `command`/`shell` without `changed_when`, or `latest` package state. Fix the task, not the test.
- A passing Molecule run on one image says nothing about another distribution's package names and paths.
