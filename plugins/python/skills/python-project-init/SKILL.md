---
name: python-project-init
description: Initializes a new Python project with uv, ruff, mypy, pytest, a Makefile, pre-commit, GitHub CI and AGENTS.md, following the structure of the team's data-platform repos, then installs this hub's python skills into it. Use when asked to create, bootstrap, scaffold or initialize a Python project, service, library or ETL repo. Do NOT use to add a module or source to an existing project.
metadata:
  always: 'false'
---

# Initialize a Python project

`scripts/init_project.py` renders the bundled templates into a new directory. The templates encode the shared skeleton of the team's two data-platform repos, minus their known mistakes, plus a few practices from public projects ([references/structure.md](references/structure.md)).

## Workflow

```
- [ ] 1. Collect inputs
- [ ] 2. Dry run, show the plan
- [ ] 3. Apply
- [ ] 4. Install the hub's python skills
- [ ] 5. Verify: make install, format, lint, typecheck, lint-yaml, unit-tests
- [ ] 6. Report
```

### 1. Inputs

Ask only for what is missing. Use the default when the user has no preference.

| Input | Flag | Default |
|---|---|---|
| Directory | positional | required |
| Name, lowercase with hyphens | `--name` | required |
| Import package | `--package` | name with underscores |
| One-line description | `--description` | `<name> Python project` |
| Minimum Python | `--python` | `3.12` |
| Line length | `--line-length` | `140` |
| Layout | `--layout app\|lib` | `app` |

- `app`: `src/` is the import root (`from src.x import y`), nothing is installed. Use it for services, pipelines and scripts.
- `lib`: `src/<package>/` with a hatchling build and a `py.typed` marker, installed and versioned. Use it when other repos import the code.
- Google style says 80 columns. Both team repos use longer lines, so the default is 140. Use another value only on request.

If the project is a pipeline, a monorepo or sits next to a shared library, read [references/structure.md](references/structure.md) before choosing a layout.

### 2. Dry run

```bash
python3 scripts/init_project.py DEST --name NAME [flags]
```

Without `--apply` it prints every file and writes nothing. Show the plan to the user. The script never overwrites: if any target exists it lists the conflicts, writes nothing and exits 1. Offer a different directory or merging by hand. Never delete or overwrite a user's file to get past a conflict.

### 3. Apply

Run the same command with `--apply`. The script does not run `git init`. Run it in `DEST` if the directory is not a repository yet.

### 4. Install the hub's python skills

Copy every python skill of this hub into `DEST` with the `/scaffold-repo` command (the `scaffold-agent-repo-cc` skill for Claude Code, `scaffold-agent-repo-codex` for Codex):

1. List `skills/python/` and take every skill except `python-project-init`. Do not hardcode the names, new python skills must be included. Add `code-review` from `skills/review/`.
2. Run `/scaffold-repo claude DEST <comma-separated names>`, or `codex` for a Codex user.
3. Run its dry run first, show it, then apply.

It writes the skills, a manifest with the hub revision, and a `CLAUDE.md` if none exists. Skip this step only if the user does not want agent skills.

### 5. Verify

In `DEST`, in this order, each must pass:

```bash
make install
make format
make lint
make typecheck
make lint-yaml
make unit-tests
```

`make format` is part of the step because a line length other than 140 can reflow the example test. When something fails, fix the generated file and say what you changed. Do not disable a rule or lower `COV_FAIL_UNDER` to pass. Needs `uv` and network access for `make install`.

### 6. Report

List the layout that was created, the verify results, and the next steps for the user:
- `cp .env.example .env` and fill in real values.
- Commit `uv.lock` (created by `make install`). CI runs `uv sync --locked` and fails without it.
- Delete the example module and its test when real code lands.
- Raise `COV_FAIL_UNDER` as the suite grows.
- Review `.github/workflows/ci.yaml` and enable branch protection requiring the CI job.

## What you get

```text
pyproject.toml   uv, ruff (E F I UP B SIM D, Google docstrings), mypy strict, pytest, coverage
Makefile         install, format, lint, typecheck, lint-yaml, unit-tests [path=], cleanup, help
scripts/ci.sh    run_unit_test and cleanup, only listed functions are callable
configs/         .pre-commit-config.yaml, .yamllint
.github/         workflows/ci.yaml, pull_request_template.md, commit_template.md
src/ + tests/    one documented example module with parametrized tests
AGENTS.md  README.md  .env.example  .gitignore
```

## Gotchas

- The workflow pins are copied from the team repos. Check the action versions in `.github/workflows/ci.yaml` against current releases when a project is created, and keep them pinned to a commit SHA.
- mypy runs in strict mode on `src/` only. Loosen it per module in `pyproject.toml` rather than turning strict off.
- `exclude-newer = "7 days"` in `pyproject.toml` refuses packages released in the last week. Remove it only when a fix is needed urgently.
- Add a dependency group (for example `ci`) only when two groups conflict, such as a Databricks Connect environment next to PySpark.
- `.claude/skills/` is excluded from ruff because it holds hub skills, not project code. Do not edit those files in the project. To update them, rerun `/scaffold-repo` with `--force` for the named skills.
- The manifest pins the hub's current commit. Commit the hub's pending skill changes first, or the pin points to a revision without them.
- Do not run the script in a directory with unsaved work you care about without the dry run. It only creates files, but conflicts abort the whole run.
