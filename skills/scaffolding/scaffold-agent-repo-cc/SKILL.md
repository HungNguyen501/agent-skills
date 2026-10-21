---
name: scaffold-agent-repo-cc
description: Installs chosen hub skills into a destination repo in the Claude Code layout (.claude/skills/NAME/, CLAUDE.md, plus a manifest) with a dry-run plan first. Use when setting up a new or existing repo for Claude Code, or adding hub skills to it, given skill names from this hub. Not for the Codex layout (use scaffold-agent-repo-codex) and not for writing a new skill (use writing-agent-skills).
license: Apache-2.0
metadata:
  always: "false"
---

# Scaffold a repo for Claude Code

Copies hub skills by name into a destination repo where Claude Code discovers them. The hub stays the source of truth; the destination holds pinned copies.

## Layout produced

```
<dest>/
├── CLAUDE.md
├── .claude/settings.example.json   shared permissions template
├── .claude/skills/
│   ├── .hub-skills.json   installed names and the hub git SHA
│   └── <skill-name>/      one folder per skill, without evals/
```

Also adds `.claude/settings.local.json` to `.gitignore`. Commit `settings.example.json`, never the local file.

## Workflow

1. **Collect inputs**: destination repo path, the skill names, and the hub path (the current repo unless told otherwise). If the user gives a domain or topic rather than names, list `skills/*/*/` and propose names. Do not guess.
2. **Plan**: run `python scripts/scaffold.py --hub HUB --dest DEST --skills a,b --dry-run`. It prints every copy and whether CLAUDE.md is written or kept.
3. **Fix errors**: an unknown name prints the available names; pick from those. An existing destination skill needs the user's go-ahead before `--force`.
4. **Apply**: show the plan to the user, then rerun without `--dry-run`.
5. **Tell the user** to fill in the project section of CLAUDE.md and to commit the generated files.

## Gotchas

- The destination must already exist; the script does not create or `git init` it.
- An existing CLAUDE.md is never overwritten. Skills are listed only in a newly written file; for an existing one, say what to add by hand.
- Copies go stale. To update, rerun with `--force` for the named skills and compare `hub_revision` in the manifest.
- Install the smallest set that fits (one to three skills active per task). Do not install a whole domain by default.
- Hub skills hold domain knowledge only. Put project-private facts in the destination's own CLAUDE.md or its own skills.
