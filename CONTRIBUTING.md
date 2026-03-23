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
pytest -q
```

To apply Ruff’s formatter when `ruff format --check` fails:

```bash
ruff format src tests
```

## CI

GitHub Actions runs those steps on push and pull requests (see [.github/workflows/ci.yml](.github/workflows/ci.yml)). If you do not use GitHub, reproduce the same steps in your automation or run them locally before merge.

## Scope

Stay within the bridge’s mission and tool contracts in [docs/MISSION.md](docs/MISSION.md) and [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md).

## Releases

To cut a bridge release, bump `[project].version` in `pyproject.toml`, add a dated section to [CHANGELOG.md](CHANGELOG.md) (Keep a Changelog style) describing user-visible changes, and if upstream **replayt** minor or major releases change behavior or APIs the bridge relies on, widen or narrow the `replayt` constraint in `pyproject.toml`, update the compatibility table in [README.md](README.md), and adjust the `replayt-floor` job pin in [.github/workflows/ci.yml](.github/workflows/ci.yml) when the declared minimum moves. Merge to the default branch with green CI, then tag the commit (for example `v0.1.0`) so integrators can pin this package while choosing their own exact replayt version inside the declared range.
