---
name: ansible-roles-playbooks
description: How to structure Ansible automation - the landscape, type, function, component hierarchy, role layout, defaults vs vars, argument_specs validation, per-OS handling, handlers, README, playbooks as role lists and tag rules. Use when creating or restructuring a role or playbook, deciding where logic belongs, or reviewing role design. Do NOT use for inventory layout (ansible-inventory-vars) or task-level style (ansible-code-style).
metadata:
  always: "false"
---

# Ansible roles and playbooks

Source: Red Hat CoP [automation good practices](https://github.com/redhat-cop/automation-good-practices) (structures, roles, playbooks).

## Structure: landscape, type, function, component

| Level | Is | Implemented as |
|---|---|---|
| Landscape | Everything deployed together | `playbooks/site.yml` that imports type playbooks (or a controller workflow) |
| Type | One kind of host. Each host has exactly one type. | One playbook per type, `playbooks/<type>.yml` |
| Function | Reusable capability (base OS, nginx, postgres client) | A role |
| Component | A maintainable slice of a function (DNS, NTP, SSH) | A task file in the role, `tasks/<component>.yml` |

Rules of thumb:
- A type playbook is a list of roles. Logic lives in roles, not playbooks.
- Never number playbooks or document a call order. If order matters, import them from `site.yml`.
- Split a component into its own role only when the task file grows unwieldy or another function needs it.
- Use `roles:` or `tasks:` in one play, not both: their execution order is not obvious. Use `tasks:` with `ansible.builtin.import_role` when you need per-role tags or conditions.

## Role layout

```text
roles/<role_name>/
├── defaults/main.yml        user-tunable inputs, all prefixed <role_name>_
├── vars/main.yml            constants and internal values, prefixed __<role_name>_
├── vars/<OS family>.yml     per-platform values
├── tasks/main.yml           imports component files, nothing else
├── tasks/<component>.yml    sub-tasks, names prefixed "<component> | "
├── handlers/main.yml
├── templates/               *.j2
├── meta/main.yml            galaxy_info, dependencies (keep empty if possible)
├── meta/argument_specs.yml  input validation and docs
├── molecule/default/        converge.yml, verify.yml, molecule.yml
└── README.md
```

- Role names: lowercase letters, digits and underscores. Hyphens break collection packaging and fail `ansible-lint` `role-name`.
- Name it for the function, not the host or customer: `nginx`, not `web01_setup`.
- **defaults vs vars**: `defaults/` is the public API, low precedence, meant to be overridden from inventory. `vars/` is internal and hard to override. Never put a value in `vars/` that a caller may reasonably change.
- Every default has a comment, and the README lists each variable, its type and default. Update both when a variable changes.
- `meta/argument_specs.yml` validates inputs before any task runs. Mark `required: true` for values with no safe default. Fail early with a clear message, not halfway through a deploy.
- Do not hardcode host group names in a role. Take them as a variable or avoid the dependency.
- Do not hardcode environment values (hosts, URLs, image tags) in a role. They come from inventory.

## Platforms and providers

- Load per-OS values with `ansible.builtin.include_vars` and `with_first_found` over `ansible_facts['distribution']`, `os_family`, then `default.yml`. Avoid long `when: ansible_os_family == ...` chains.
- Use `ansible_facts['x']`, not injected `ansible_x`.
- Separate tasks per provider or OS into files selected the same way.
- Support check mode: a role must not fail in `--check` and must report no change on a second run.

## Handlers

- Put restart and reload in handlers, notified by the task that changed config. Name them like `Restart nginx`.
- Validate config before it lands: `validate:` on `template`/`copy` (for example `nginx -t -c %s`).
- Need a restart mid-play: `ansible.builtin.meta: flush_handlers`.

## Playbooks

- A play: `name`, `hosts` (a group, never `all` with a destructive role), `gather_facts` only when used, `become` only when needed.
- Do not mix unrelated services in one play.
- `serial` and `max_fail_percentage` on plays that touch live traffic. See the `ansible-safe-deploys` skill.
- Tags: one tag per role (the role name) for dev, plus a few documented purpose tags (`deploy`, `configure`). Never add a tag that is destructive or useless alone. One tag should be enough to get a meaningful result.
- `debug` tasks carry `verbosity:` so production output stays clean.

## Reuse before writing

1. Check `ansible-doc` and the collections already in `requirements.yml` for a module.
2. Check for a maintained collection role (for example `community.general`, `ansible.posix`, vendor collections).
3. Write a role only for behavior that does not exist, or that you must own. Do not add a role, flag or variable for a single call site with no second consumer.

## Gotchas

- Role dependencies in `meta/main.yml` run before the role and cannot be skipped by tags. Prefer an explicit role list in the playbook.
- `include_role` hides tasks from `--list-tasks` and static analysis. Use `import_role` unless the name is dynamic.
- A role variable set with `set_fact` outlives the role and leaks to later plays. Use `vars:` on the task or a `__role_` internal name.
- Task file names, variables and handler names are global across roles. Prefixes are what prevent collisions.
