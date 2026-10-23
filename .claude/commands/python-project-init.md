---
description: Initialize a new Python project (uv, ruff, mypy, pytest, CI, AGENTS.md) and install the hub's python skills
argument-hint: <dest-path> [project-name] [--layout app|lib] [--python 3.12] [--line-length 140] [--description "..."]
---

Parse $ARGUMENTS as destination path, optional project name and optional flags. If the destination is missing, ask for it. Default the name to the destination's folder name in lowercase with hyphens.

Follow the `python-project-init` skill (`skills/python/python-project-init/SKILL.md` in this repo). The hub is this repo. Run the dry run first and show it before applying. Then install the hub's python skills and the `code-review` skill into the destination as its step 4 says, and verify the new project.
