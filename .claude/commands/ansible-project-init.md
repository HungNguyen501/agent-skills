---
description: Initialize a new Ansible project (uv, ansible-lint, Molecule, vault, check-then-apply CI, AGENTS.md) and install the hub's ansible skills
argument-hint: <dest-path> [project-name] [--environments staging,production] [--connection ssh|ssm] [--python 3.12] [--description "..."]
---

Parse $ARGUMENTS as destination path, optional project name and optional flags. If the destination is missing, ask for it. Default the name to the destination's folder name in lowercase with hyphens.

Follow the `ansible-project-init` skill (`skills/ansible/ansible-project-init/SKILL.md` in this repo). The hub is this repo. Run the dry run first and show it before applying. Then install the hub's ansible skills into the destination as its step 4 says, and verify the new project.
