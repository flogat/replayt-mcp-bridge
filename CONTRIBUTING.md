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

The default **`pytest -q`** run collects **`tests/test_mcp_server_stdio.py`** (bridge subprocess starts **without a Python traceback**, no MCP traffic) and **`tests/test_mcp_stdio_session_smoke.py`** (MCP SDK client over real stdio: **initialize**, **tools/list**, **`replayt_version_info`**). Failures there usually mean broken stdio wiring, tool registration, or a hung/broken child process—see [docs/MISSION.md](docs/MISSION.md#stdio-mcp-session-integration-smoke-test).

To apply Ruff’s formatter when `ruff format --check` fails:

```bash
ruff format src tests
```

## CI

GitHub Actions runs those steps on push and pull requests (see [.github/workflows/ci.yml](.github/workflows/ci.yml)) on **CPython 3.11, 3.12, and 3.13**; a separate **`replayt-floor`** job pins the minimum **replayt** release on 3.11. If you do not use GitHub, reproduce the same steps in your automation or run them locally before merge—ideally on the same minor you deploy.

## MCP host snippets (`docs/MCP_HOST_CONFIG.md`)

When you edit copy-paste JSON or host-specific notes, keep placeholders generic (no real API keys, tokens, or machine-specific home paths) and preserve an explicit **stdio** story per host (stdin/stdout MCP, or the host’s **`type: "stdio"`** field where required). To validate that your snippet still matches a working launch, install the bridge in a venv and use the same **`command`** and **`args`** as in the doc, then attach your MCP client and confirm the server is **active** and **`replayt_version_info`** (or at least **`tools/list`**) succeeds. From the repo root you can also run **`pytest tests/test_mcp_stdio_session_smoke.py -q`**, which drives **`python -m replayt_mcp_bridge`** over real stdio with the MCP Python SDK (handshake plus one tool call). **`pytest tests/test_mcp_host_config_docs.py -q`** guards required doc strings, upstream links, and README wiring.

## Scope

Stay within the bridge’s mission and tool contracts in [docs/MISSION.md](docs/MISSION.md) and [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md).

## Releases

To cut a bridge release, bump `[project].version` in `pyproject.toml`, add a dated section to [CHANGELOG.md](CHANGELOG.md) (Keep a Changelog style) describing user-visible changes, and if upstream **replayt** minor or major releases change behavior or APIs the bridge relies on, widen or narrow the `replayt` constraint in `pyproject.toml`, update the compatibility table in [README.md](README.md), and adjust the `replayt-floor` job pin in [.github/workflows/ci.yml](.github/workflows/ci.yml) when the declared minimum moves. Merge to the default branch with green CI, then tag the commit (for example `v0.1.0`) so integrators can pin this package while choosing their own exact replayt version inside the declared range.
