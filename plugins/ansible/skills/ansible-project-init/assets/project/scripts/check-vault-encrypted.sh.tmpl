#!/usr/bin/env bash
# Fails when a vault.yml passed as an argument is not Ansible Vault ciphertext. A vault file that was decrypted and saved is the usual leak.
# Usage: check-vault-encrypted.sh FILE...
set -euo pipefail

status=0
first_line=
for file in "$@"; do
    if [ ! -f "${file}" ]; then
        echo "error: ${file} not found" >&2
        status=1
        continue
    fi
    IFS= read -r first_line <"${file}" || true
    if [[ "${first_line}" != '$ANSIBLE_VAULT;'* ]]; then
        echo "error: ${file} is not vault-encrypted. Run: ansible-vault encrypt ${file}" >&2
        status=1
    fi
done
exit "${status}"
