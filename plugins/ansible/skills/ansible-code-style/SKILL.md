---
name: ansible-code-style
description: Conventions for writing and reviewing Ansible YAML, tasks, variables, Jinja2 and templates - FQCN, task names, variable naming, idempotent command use, check mode, no_log and ansible-lint production profile. Use when writing or reviewing playbooks, task files or templates, or when ansible-lint or yamllint reports findings. Do NOT use for role directory design (ansible-roles-playbooks) or secret storage (ansible-vault-secrets).
metadata:
  always: "false"
---

# Ansible code style

Based on the Red Hat Communities of Practice [automation good practices](https://github.com/redhat-cop/automation-good-practices) and the `ansible-lint` production profile. Ansible is not Python: prefer plain, declarative tasks over clever Jinja2.

## Rules

| Area | Rule |
|---|---|
| Modules | Fully qualified names: `ansible.builtin.copy`, not `copy`. Short names break when a collection shadows them. |
| Task names | Every task has a `name:` that starts with a capital letter and says the outcome ("Install nginx package"). No trailing period. |
| Play names | Every play has a `name:`. |
| YAML | `.yml` everywhere, two-space indent, `true`/`false` booleans, list items indented under the key. Quote a string that starts with `{{`, `*`, `&`, `:` or looks like a number or `yes`/`no` when you mean text. |
| Modes | File modes are quoted strings with a leading zero: `mode: "0644"`. Set `mode`, `owner` and `group` explicitly on copy, template and file. |
| Variables | `snake_case`. Role variables start with the role name (`nginx_port`). Variables the role sets internally start with `__rolename_`. Do not reuse a name across roles. |
| Booleans in `when` | `when: nginx_enabled`, not `when: nginx_enabled == true`. A list under `when:` means AND. |
| Jinja2 | One space inside braces: `{{ var | default('x') }}`. Keep logic in tasks and vars, not templates. A template with more than a few conditionals wants a role variable instead. |
| Line length | Wrap long strings with `>-` or `|`. No long one-liner `shell`. |
| Comments | Explain why, not what. Put a comment above a non-obvious `changed_when`, `ignore_errors` or `become`. |

## Idempotence and check mode

- Use a module when one exists. `shell` and `command` are the last resort, and `command` beats `shell` unless you need pipes or redirects.
- A `command`/`shell` task needs `creates:` or `removes:`, or an honest `changed_when:`. Read-only probes get `changed_when: false`.
- A task that registers a result for later tasks must still work under `--check`. Set `check_mode: false` on read-only probes, or guard dependents with `when: not ansible_check_mode`.
- `ignore_errors: true` hides real failures. Use `failed_when:` with a narrow condition, or `block`/`rescue`.
- Network calls (package install from URL, image pull, API call) get `retries`, `delay` and `until`.
- Prefer a handler over a restart task. Handlers fire once at the end of the play and only on change.

## Secrets in tasks

- `no_log: true` on any task that handles a password, token or key, including `uri`, `template` of a secrets file and `command` with a secret in an argument.
- Never `debug` a secret. Give other debug tasks `verbosity: 1` or higher.
- Keep secret files `mode: "0600"`.

## Linting

Run `ansible-lint` with `profile: production` and `yamllint`. See the `ansible-testing` skill for configuration. Fix findings; do not add a rule to `skip_list` without a one-line reason in the config file beside it.

## Gotchas

- `become: true` at play level runs every task as root. Set it on the tasks that need it, or at play level only when all tasks do.
- `when:` conditions are already Jinja2. Do not wrap them in `{{ }}`.
- `with_items` is legacy. Use `loop:`.
- `include_tasks` is dynamic: tags and `--list-tasks` do not see inside. Use `import_tasks` for static structure.
- A variable defined in `vars:` of a play beats `group_vars` and cannot be overridden by inventory. Put tunables in role `defaults/` and inventory.
- `latest` for packages or image tags makes a rerun change the system. Pin versions, or accept drift on purpose and document it.
- `ansible.builtin.copy` with `content:` of a Jinja2 string hides the template from linting. Use a `.j2` file and `template`.
