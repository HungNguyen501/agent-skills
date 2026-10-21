---
description: Install hub skills into another repo for Claude Code or Codex
argument-hint: <claude|codex> <dest-repo-path> <skill-name[,skill-name...]>
---

Parse $ARGUMENTS as target, destination path and comma-separated skill names. If any is missing, ask for it.

Use the `scaffold-agent-repo-cc` skill when the target is claude, or `scaffold-agent-repo-codex` when it is codex. The hub is this repo. Run the dry run first and show it before applying.
