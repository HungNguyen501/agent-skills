---
name: ansible-safe-deploys
description: Safe execution of Ansible against live hosts - check then apply, --diff review, serial batches and max_fail_percentage, limits and tags, one environment at a time, rollback plans, GitHub Actions check and apply workflows with typed confirmation, and rules for coding agents running playbooks. Use when running, planning or reviewing a deploy, designing a deploy pipeline, or asked to apply changes to staging or production. Do NOT use for writing roles (ansible-roles-playbooks) or lint and Molecule setup (ansible-testing).
metadata:
  always: "false"
---

# Safe Ansible deploys

Source: Red Hat CoP [automation good practices](https://github.com/redhat-cop/automation-good-practices) (CI/CD and promotion) and the Ansible docs on check mode and rolling updates.

## Workflow for any live change

```
- [ ] 1. State the change, the target environment, and the rollback plan
- [ ] 2. Lint and syntax-check pass
- [ ] 3. Staging: --check --diff, review, apply, verify
- [ ] 4. Production: --check --diff, review the diff with a second person, apply
- [ ] 5. Verify service health, record what was run
```

- One environment at a time. Staging first, and production only after staging was verified with the same commit.
- Explicit inventory every time: `-i inventories/<env>`. Never rely on a default inventory.
- Dry run first: `ansible-playbook -i inventories/<env> playbooks/<x>.yml --check --diff`. Read the diff. An unexpected change is a stop, not a note.
- Limit the blast radius: `--limit <host or group>`, `--tags <purpose>`. Start with one host (a canary) before the group.
- A dry run does not prove the apply. Some tasks cannot predict their effect in check mode. Verify after applying.

## Rolling out safely

```yaml
- name: Update web tier
  hosts: web
  serial: [1, "25%", "100%"]     # canary, then a quarter, then the rest
  max_fail_percentage: 0          # any failure stops the rollout
  roles:
    - role: nginx
```

- `serial` for anything behind a load balancer or sharing state. A small first batch makes a bad change touch one host.
- `max_fail_percentage` (or `any_errors_fatal: true`) so a failing batch halts the run.
- Health-check between batches: a task that asserts the service answers (`ansible.builtin.uri` with `retries`/`until`), failing the host before the next batch.
- Take out of rotation, change, put back, in that order. Failing mid-way must not leave a host out of rotation without a visible failure.

## Rollback

Decide before applying, and write it in the change record.
- Config: previous version in git, redeploy the prior commit. Roles must tolerate rerunning an older version.
- Packages and images: pinned previous version in inventory, redeploy it.
- Data or schema changes: Ansible does not undo them. Take a backup first and say who restores it.
- Rollback by "run it forward again" only works if the playbook is idempotent. See the `ansible-testing` skill.

## CI/CD: check, then apply

Two workflows, both `workflow_dispatch`, both bound to a GitHub environment.

1. **Check**: runs `--check --diff`, writes the diff to the job summary and an artifact. Changes nothing.
2. **Apply**: takes the `check_run_id` of a successful check run on the **same commit** and a typed confirmation `apply-<environment>`. It verifies both before running anything.

Hardening for either workflow:
- Treat inputs as untrusted. Pass them through `env:` and quote them in the shell. Never interpolate `${{ inputs.x }}` into a `run:` script. Restrict `playbook` to a path under `playbooks/` that exists, and `limit`, `tags` to a safe character set.
- `permissions:` minimal: `contents: read`, `id-token: write` on the deploy job, `actions: read` on apply to check the earlier run.
- Cloud access by OIDC. Vault password from an environment secret, written to a `0600` temp file, removed in an `if: always()` step. See the `ansible-vault-secrets` skill.
- `concurrency:` per environment so two applies never overlap, with `cancel-in-progress: false`.
- Record who ran what: keep the run logs and the check artifact. They are the audit trail. Add a chat or ticket notification on completion.
- Branch protection (required reviews and checks on the default branch) is the control when the plan has no environment approvals. Say so in the repo docs.

## Rules for coding agents

- Do not run `ansible-playbook`, `make deploy`, or trigger an apply workflow unless the user explicitly asks in this conversation. Running `--check` against production hosts also needs the request.
- Ask before changing production inventory, vault files or production playbooks. Changes there need a recorded plan.
- Prefer proposing the command. Show the exact `--check --diff` command and let the user run it, unless told to run it.
- Never skip the check step for production. Never answer "apply" to a request that said "check".
- Do not decrypt vault files or print secrets to make a deploy work.
- If the repo state or target environment is unclear, read the playbook and inventory first, then ask.

## Gotchas

- A `--limit` that matches no host only warns and exits 0. Check the play recap lists the hosts you meant.
- `--check` skips `command`/`shell` tasks without `check_mode: false`, so the diff understates what the apply does.
- `serial` changes handler timing: handlers flush per batch, not once at the end.
- `--tags` skips untagged tasks and any setup the tagged tasks need. Tags must be usable alone.
- `gather_facts: false` plus a task that reads `ansible_facts` fails mid-run. Gather facts in plays that use them.
- A stale `check_run_id` from another commit proves nothing. The apply workflow must compare commit SHAs.
