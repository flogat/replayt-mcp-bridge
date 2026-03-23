# Contributing

## Environment

Use a **project virtualenv** (see [README.md](README.md) Quick start). On Windows, avoid mixing system Python with `pip install --user` when working on this package; a dedicated `.venv` keeps installs and console scripts consistent.

Install the package in editable mode **with dev extras** so lint tools match CI:

```bash
pip install -U pip
pip install -e ".[dev]"
```

`pytest` is also pulled in by the base editable install (`pyproject.toml`); `ruff` comes from the `dev` extra.

## Checks before you open a PR

Run the same commands CI uses, in order (any failure should block the PR):

```bash
ruff check src tests
ruff format --check src tests
pytest
```

To apply Ruff’s formatter when `ruff format --check` fails:

```bash
ruff format src tests
```

## CI

GitHub Actions runs those steps on push and pull requests (see [.github/workflows/ci.yml](.github/workflows/ci.yml)). If you do not use GitHub, reproduce the same steps in your automation or run them locally before merge.

## Scope

Stay within the bridge’s mission and tool contracts in [docs/MISSION.md](docs/MISSION.md) and [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md).
