# Packaging and distribution

## Contents
- Repo layout
- Claude Code plugins
- Other harnesses
- Custom runtimes
- Versioning
- Local configuration

## Repo layout

The hub keeps one source of truth, `skills/<domain>/<skill-name>/`, and generates everything else with `scripts/build.py`. Never edit generated files: `plugins/` and `.claude-plugin/marketplace.json`. CI fails if they are out of date.

Third-party skill repos live under `vendor/` as submodules pinned to a commit.

## Claude Code plugins

- `.claude-plugin/marketplace.json` lists plugins, one per domain.
- Each plugin has `.claude-plugin/plugin.json` and a `skills/` directory.
- Users install by domain, so a project loads only the domains it needs.
- Skill directory names are lowercase and hyphenated.
- `strict: true` blocks loading when any skill fails validation. `strict: false` loads skills independently.
- Slash commands are namespaced by plugin.

## Other harnesses

- Harnesses differ in discovery paths and in how they discover skills. Do not assume a skill behaves the same everywhere.
- Generate per-target output from the single source rather than hand-copying skills between directories.
- Check each harness's current documentation for its skill directory before adding a target.

## Custom runtimes

For agents that call an LLM API directly (for example an OpenAI function-calling bot):
- Pin the hub as a git submodule and load the skills you need with `runtimes/python/loader.py`, passing the domain directories to `discover()` and an `allow` list for routed skills.
- Three loading modes: `router` (a small model picks skills from the menu), `tool` (the model calls `load_skill` and `read_skill_file`), `eager` (inject all).
- Keep runtime-specific text (tool names, output formatting) in the consumer repo, not in hub skills.

## Versioning

- Tag releases. A tag maps to exactly one published version.
- In patch releases, do not change script arguments, reference file paths or `SKILL.md` structure.
- Consumers pin a tag or SHA and update through a pull request.

## Local configuration

Commit `settings.example.json`, never `settings.local.json`. Environment variables live in the directory that launches the agent.
