# Project structure reference

## Contents
- Shared skeleton
- Variant: pipeline app
- Variant: platform monorepo
- Variant: installable library
- Conventions worth keeping
- Do not copy

Read this when the project is more than one plain package: an ETL or orchestration repo with one folder per data source, a monorepo with several packages, or a shared library next to an app. The generated starter covers the shared skeleton only.

## Shared skeleton

Both team repos (an Airflow ETL repo and a Databricks platform repo) share this shape. The starter generates all of it except the agent layer, which `/scaffold-repo` installs:

- `pyproject.toml` with `uv`, ruff, pytest and coverage config in one file. `[tool.uv] package = false` for apps.
- `Makefile` as the single command surface: `install`, `lint`, `lint-yaml`, `unit-tests`, `cleanup`, `help`. CI and agents call the same targets as people.
- `scripts/ci.sh` holds the shell behind the targets. `scripts/hooks/` holds agent hooks.
- `configs/` holds tooling config (pre-commit, yamllint). `.github/` holds workflows and the PR and commit templates.
- `AGENTS.md` for shared agent instructions, a short `CLAUDE.md` that imports it, and `.claude/` for rules, commands, agents and skills.
- `.env` gitignored, `.env.example` committed with placeholders.
- `tests/` mirrors the source tree.

## Variant: pipeline app

An Airflow ETL repo. One folder per upstream source, thin orchestration over logic:

```text
dags/                  one etl_<source>.py per pipeline, thin wrapper that calls the job
src/jobs/<source>/etl.py   fetch, bronze, silver logic for one source
src/config/ingest_<source>.yaml   declarative per-table config, templated
src/schemas/bronze/<source>/      schema contracts used when unnesting
src/common/            shared clients and table classes (alerts, config access, cloud helpers)
tests/                 mirrors src/
```

Rules the repo follows: match the closest existing source before inventing a shape, keep DAG files free of logic, keep secrets in the orchestrator's variable store and register each new one in a single config class.

## Variant: platform monorepo

A Databricks platform with several packages under `core/`:

```text
core/<platform>/src/{bronze,silver,gold}/<vendor>/   one folder per vendor and layer
core/<platform>/schemas/{bronze,silver,gold}/<vendor>/   mirrors src/
core/<platform>/configs/{dev,prod}/                  config-driven objects, per environment
core/<platform>/tests/
core/<lib>/{src,tests}/                              shared library with its own pyproject
databricks.yml, resources/                           deployment bundle
```

Consequences for the tooling: `make unit-tests path=core/<pkg>` takes the package directory, pytest `testpaths` lists every `tests/` folder, and the shared library is installed editable (`uv pip install -e core/<lib>`) before the app tests run. Use `--layout app` for the root and run the init per package only when a package needs its own `pyproject.toml`.

## Variant: installable library

A wheel consumed by other repos. Use `--layout lib`: `src/<package>/` with a hatchling `[build-system]`, a `py.typed` marker, `package = true`, tests importing `<package>`, and a version bumped per release. The library has its own Makefile and pyproject when it lives inside a monorepo.

## Conventions worth keeping

- Mirror trees: `src/`, `schemas/` and `tests/` follow the same folder names, so a reader finds the test and the contract by path.
- One folder per source or vendor, named after it, with the same inner file names in each.
- Declarative config (YAML) apart from code, validated by a test that loads every shipped file.
- Generic workflows behind a helper CLI and Make targets. Do not add a new target when one covers it.
- Tooling config under `configs/`, not the root.

## Do not copy

These show up in the source repos and are mistakes:

- `build-backend = "poetry-core"` together with `package = false`. The backend is never used.
- A `pyproject.toml` `testpaths` copied from another repo, pointing at folders that do not exist, so pytest collects nothing.
- A CI that runs lint only and never runs the tests.
- Three overlapping linters (ruff, flake8, pylint) over the same rules. Ruff alone covers them. Add one back only for a rule ruff lacks.
- A `ci.sh` that ends with `$*`, which runs any command passed to it. The starter allows only listed functions.
- Style rules that "make lint does not enforce". Enable ruff `I` and `D` so import order and docstrings are checked.
- Stray `pyproject.toml.bak` files. Use git history.

## Practices borrowed from public projects

Only what several of them share:

- Type checking with mypy, strict on the package: Google's adk-python (`strict = true`) and Microsoft's markitdown (mypy in its hatch env).
- Hatchling as the library build backend: Apple's axlearn and Microsoft's markitdown. Google's adk-python uses flit. A `py.typed` marker ships with typed libraries (adk-python).
- Ruff for lint and format with Google-convention docstrings (`D`) and import sorting (`I`): Microsoft's semantic-kernel and Apple's axlearn.
- Pytest with `-ra`, registered markers and a `testpaths` that exists: semantic-kernel, axlearn. The starter adds `--strict-markers --strict-config` so a typo fails fast.
- Branch coverage with `if TYPE_CHECKING:` and `if __name__ == "__main__":` excluded: markitdown.
- GitHub actions pinned to a full commit SHA with the version in a comment, and `contents: read` permissions: markitdown.

Left out on purpose to keep the starter small: tox or hatch test matrices, codespell, bandit, a Python version matrix in CI, pinned tool versions, and repo-policy files (security policy, code owners, dependabot). Add them per project when needed.
