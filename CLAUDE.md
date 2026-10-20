# agent-skills hub

Central hub of agent skills. Source of truth is `skills/<domain>/<skill>/`. Read `skills/authoring/writing-agent-skills/SKILL.md` before creating or editing any skill.

## Commands

- `uv run pytest` runs the tests. They mirror the source tree (`tests/scripts/test_<module>.py`, `tests/runtimes/python/test_loader.py`); shared builders live in `tests/mocks.py`.
- `uv run python scripts/validate.py` checks all skills under `skills/`.
- `uv run python scripts/build.py` regenerates `plugins/` and `.claude-plugin/marketplace.json`. `--check` verifies only.

## Rules

- Never hand-edit generated files (`plugins/`, `.claude-plugin/`). Run build.py instead.
- Never edit `vendor/`. It holds pinned third-party submodules and is skipped by validate.py.
- Hub skills hold domain knowledge only. Do not name a consumer's runtime tools or output format.
- Skill names are unique across the whole hub.
- Write evals before the skill body. Each skill needs at least 3 in `evals/evals.json`.
- Commit a skill together with the regenerated files.
