---
name: ansible-inventory-vars
description: Inventory and variable design for Ansible - one directory per environment, group_vars and host_vars as directories, plaintext vars.yml beside encrypted vault.yml, single source of truth, as-is vs to-be data, variable precedence and extra-vars limits. Use when adding hosts or variables, creating an environment, choosing where a value lives, or debugging which value won. Do NOT use for encrypting secrets (ansible-vault-secrets) or role internals (ansible-roles-playbooks).
metadata:
  always: "false"
---

# Ansible inventory and variables

Source: Red Hat CoP [automation good practices](https://github.com/redhat-cop/automation-good-practices) (inventories) and the Ansible variable precedence docs.

## Layout

One inventory directory per environment. Nothing is shared between environments, so a change to one cannot reach another.

```text
inventories/
├── staging/
│   ├── hosts.yml                  static hosts and groups (or a dynamic plugin config beside it)
│   ├── group_vars/
│   │   ├── all/
│   │   │   ├── vars.yml           plaintext, non-sensitive
│   │   │   └── vault.yml          encrypted secrets, only vault_* names
│   │   └── <group>/{vars,vault}.yml
│   └── host_vars/<host>/vars.yml  only for true per-host exceptions
├── production/                    same shape
└── local/                         local testing only, never points at production
```

- Always pass `-i inventories/<env>` explicitly. Do not set a default `inventory =` in `ansible.cfg`, so a forgotten flag fails instead of hitting the wrong hosts.
- Pass the directory, not `hosts.yml`, so `group_vars` and any dynamic plugin files load together.
- `group_vars/all/` is the place for values common to one environment, not to all environments.
- Use a directory per group or host (`group_vars/web/vars.yml`) over a single `group_vars/web.yml`: smaller merge conflicts, and you can drop `vault.yml` in beside it.

## Where a value lives

| Value | Home |
|---|---|
| Image tag, port, feature flag, path | `vars.yml` of the group that owns it |
| Credential, key, token | `vault.yml`, name starts `vault_`. See the `ansible-vault-secrets` skill |
| Constant the role needs | The role's `vars/`, not inventory |
| Default a caller may override | The role's `defaults/` |
| One-off override for a single run | `-e`, then discard |

Wire a secret through a plaintext alias so reviewers can see what uses it:

```yaml
# vars.yml
app_db_password: "{{ vault_app_db_password }}"
```

## Single source of truth and as-is vs to-be

- Each fact has one source: the cloud API for IPs and instance IDs, a CMDB for owners, the inventory only for what exists nowhere else.
- Use dynamic inventory plugins (for example `amazon.aws.aws_ec2`) for discovered hosts. Keep their config file in the inventory directory and group by tag, not by name.
- Keep as-is data (facts, discovered values) apart from to-be data (variables describing desired state). Never use a discovered value where you mean the desired one: automation then agrees with whatever exists and drift goes unnoticed.
- Loop over inventory groups. Do not hardcode host lists in playbooks or variables.

## Precedence, the short version

Low to high: role `defaults` < inventory `group_vars/all` < `group_vars/<group>` < `host_vars` < play `vars` < role `vars` < `set_fact` < `-e` extra vars.

- Put tunables low (defaults, group_vars) so callers can override them.
- Extra vars win over everything and hide inventory values. Using `-e` for stable values makes a run impossible to reproduce from git. Keep `-e` for one-offs such as a version for a single run.
- Do not use variable types and structure tricks to merge values across groups (`hash_behaviour = merge`). Use `combine` explicitly.

## Gotchas

- A group name in `hosts.yml` that matches a directory name under `group_vars/` is how vars attach. A typo silently loads nothing. Check with `ansible-inventory -i inventories/<env> --host <host>` or `--graph --vars`.
- Hostnames and group names use underscores. Hyphens in group names are deprecated and break `groups['a-b']` patterns.
- Ansible reads `group_vars` relative to the inventory, and also relative to the playbook directory. Keep one location, the inventory.
- `ansible-inventory --host` prints decrypted vault values. Do not paste its output.
- Booleans from `-e flag=false` arrive as the string `"false"`, which is truthy. Pass JSON (`-e '{"flag": false}'`) or use `| bool`.
