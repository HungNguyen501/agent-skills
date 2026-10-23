---
name: ansible-vault-secrets
description: Handling secrets in Ansible repos - Ansible Vault files and encrypt_string, vault_ variable naming, per-environment vault password files kept outside the repo, no_log, secret scanning in pre-commit and CI, OIDC instead of stored cloud keys, and what to do when a plaintext secret is found. Use when a task touches credentials, tokens, keys, vault.yml, .env files, vault passwords or CI secrets in an Ansible project. Do NOT use for non-secret variable placement (ansible-inventory-vars).
metadata:
  always: "false"
---

# Ansible secrets

Source: Red Hat CoP [automation good practices](https://github.com/redhat-cop/automation-good-practices) (security) and the Ansible Vault docs.

## Rules

1. No secret in plaintext in git, ever: not in `vars.yml`, `hosts.yml`, templates, `.env` files, workflow files or commit messages.
2. Secrets live in vault-encrypted files or an external store (AWS Secrets Manager or SSM Parameter Store, HashiCorp Vault, a controller credential). Prefer a lookup to an external store when one exists. Vault files are the fallback.
3. One vault password per environment. A leaked staging password must not open production.
4. The vault password file lives outside the repo (for example `~/.vault/<project>_<env>`, mode `0600`). Never commit it, never put it in `ansible.cfg`.
5. Do not decrypt, view or paste a secret unless the task needs it. Decrypting is not a read-only action. Never put decrypted values in chat, logs, commit messages or `debug`.

## File pattern

```text
inventories/<env>/group_vars/all/
├── vars.yml     app_db_password: "{{ vault_app_db_password }}"
└── vault.yml    vault_app_db_password: <encrypted>   (whole file starts with $ANSIBLE_VAULT;1.1;AES256)
```

- Names in `vault.yml` start with `vault_`. `vars.yml` aliases them, so `grep` shows where a secret is used without decrypting anything.
- Commit a `vault.example.yml` with placeholder values. Copy and encrypt it to create the real file.
- Whole-file encryption hides variable names. `ansible-vault encrypt_string` produces inline values (`!vault |`), which keep names readable but make diffs and rotation harder. Choose whole-file for a vault file, inline for a single value in a shared file.

## Commands

```bash
ansible-vault create   inventories/staging/group_vars/all/vault.yml --vault-password-file ~/.vault/proj_staging
ansible-vault edit     inventories/staging/group_vars/all/vault.yml --vault-password-file ~/.vault/proj_staging
ansible-vault encrypt_string --stdin-name vault_app_db_password --vault-password-file ~/.vault/proj_staging
ansible-vault rekey    inventories/staging/group_vars/all/vault.yml --vault-password-file ~/.vault/proj_staging --new-vault-password-file <new>
```

`encrypt_string --stdin-name` reads the value from stdin, so it stays out of shell history. Typing the value as an argument (`encrypt_string 'secret'`) leaves it in history.

## Task and log hygiene

- `no_log: true` on tasks that use secrets. Without it, a failure or `-v` run prints the arguments to the console and CI log.
- Never `debug` a variable that may hold a secret.
- `--check --diff` prints the content of changed files. A task that templates a secret into a file needs `diff: false`, or the value reaches CI logs, job summaries and artifacts. `no_log` does not hide it.
- Keep rendered secret files `mode: "0600"` and owned by the service user.
- A secret in a command line shows in `ps`. Pass it by file, environment or stdin.

## Prevent and detect

- Pre-commit: a secret scanner (`gitleaks` or `detect-secrets`) plus a check that every `vault.yml` begins with `$ANSIBLE_VAULT;`. A decrypted-and-saved vault file is the common accident.
- CI runs the same scanner on every pull request, and a scheduled full-history scan.
- Enable push protection on the git host.
- `ansible-lint` and formatters must skip vault files. A text pass over ciphertext corrupts it.

## CI and cloud credentials

- Use OIDC federation (GitHub Actions to an AWS role) for cloud access. Do not store long-lived access keys.
- Store the vault password as an environment-scoped secret. Write it to a temp file with `0600` in one step, pass `--vault-password-file`, delete it in a final step that runs `if: always()`.
- Workflow `permissions:` start at `contents: read`. Add `id-token: write` only on jobs that assume a role.
- Never echo secrets or put them in step names. Pass them through `env:`.

## When a plaintext secret is found

1. Stop. Do not "fix" it silently, and do not repeat the value.
2. Tell the user. Treat the secret as compromised.
3. Rotate it at the source first. Rewriting git history does not un-leak it.
4. Add the replacement to the vault, remove the plaintext, and purge history only after rotation.
5. Add or fix the scanner that missed it.

## Gotchas

- `ansible-vault view` and `ansible-inventory --host` print secrets. Do not paste their output.
- A vault file edited in a plain editor and saved is plaintext again. Use `ansible-vault edit`.
- Changing the vault password needs `rekey` on every encrypted file and a CI secret update, in one change.
- A vault ID label (`--vault-id prod@file`) does not give separate keys by itself. It only selects which password to try. Separate passwords per environment still come from separate files.
