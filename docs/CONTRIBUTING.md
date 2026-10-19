# Contributing a skill

Read the skill [writing-agent-skills](../skills/authoring/writing-agent-skills/SKILL.md) first. It holds the full rules and the sources behind them. This page is the short version.

## Setup

```bash
git clone --recurse-submodules <repo-url>
uv sync
uv run python scripts/validate.py
```

## Add a skill

1. `cp -r template-skill skills/<domain>/<skill-name>`. Add the domain to `skills/domains.json` if it is new.
2. Write the evals first (`evals/evals.json`, at least 3 cases, one a red herring). Run a baseline without the skill.
3. Write the minimum `SKILL.md`. Replace every template placeholder.
4. `uv run python scripts/validate.py`, then `uv run python scripts/build.py`.
5. Commit the skill and the regenerated files together.

## Rules enforced in CI

- `name`: at most 64 chars, lowercase letters, digits and hyphens, equals the directory name, unique across the hub, no "claude" or "anthropic".
- `description`: at most 1,024 chars, third person, no XML tags. It should include "Use when ...".
- Custom frontmatter keys go under `metadata:` with string values. Hub keys: `always` and `order` (integer string, lower loads first).
- `SKILL.md` body at most 500 lines and about 5,000 tokens.
- References are linked from `SKILL.md`, one level deep, and files over 100 lines start with `## Contents`.
- `evals/evals.json` has at least 3 cases.
- Generated files (`plugins/`, `.claude-plugin/`, `manifest.json`) match `scripts/build.py` output.

## Hub rules

- Domain knowledge only. Do not name a consumer's runtime tools or output format in a hub skill.
- Preference skills (workflows, conventions, gotchas) are preferred over capability skills that patch model gaps.
- Never edit `vendor/`. Update a vendored repo by moving its submodule pointer in a pull request.
- Do not change script arguments, reference paths or `SKILL.md` structure in a patch release.

## Consuming skills from another repo

Claude Code and Codex repos install plugins. Custom runtimes use `scripts/sync.py` with a `skills.toml` and `runtimes/python/loader.py`. See the README.
