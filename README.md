# MCP tool bridge for replayt workflow steps

**[docs/MISSION.md](docs/MISSION.md)** — scope, non-goals, success criteria, and how this repo relates to upstream replayt.

**[CONTRIBUTING.md](CONTRIBUTING.md)** — local **pytest** / **Ruff** commands and PR expectations (aligned with CI).

**[CHANGELOG.md](CHANGELOG.md)** — release notes (Keep a Changelog).

## Compatibility with replayt

Declared support is **`replayt>=0.4.25,<0.5`** in [`pyproject.toml`](pyproject.toml). CI reinstalls **`replayt==0.4.25`** in the `replayt-floor` job to guard the lower bound; the default job resolves the latest **replayt** compatible with that range.

| Bridge version | Supported replayt (declared) | CI-tested replayt |
| -------------- | ---------------------------- | ----------------- |
| 0.1.0          | `>=0.4.25,<0.5`              | **0.4.25** (minimum); latest in range on matrix jobs |

When replayt **minor** or **major** lines change behavior or APIs this bridge uses, maintainers should bump the dependency range in `pyproject.toml`, refresh this table and [CHANGELOG.md](CHANGELOG.md), and extend CI if a new floor pin is needed. For the upcoming **0.5.x** line, see **[docs/REPLAYT_0_5_COMPATIBILITY_SPIKE.md](docs/REPLAYT_0_5_COMPATIBILITY_SPIKE.md)** (status, rerun commands, and migration draft).

## Overview

This project builds on **[replayt](https://pypi.org/project/replayt/)**. Use
**[docs/REPLAYT_ECOSYSTEM_IDEA.md](docs/REPLAYT_ECOSYSTEM_IDEA.md)** for positioning context and the chosen primary pattern.

## Design principles

**[docs/DESIGN_PRINCIPLES.md](docs/DESIGN_PRINCIPLES.md)** covers **replayt** compatibility, versioning, and (for showcases)
**LLM** boundaries.

**[docs/MCP_TOOLS.md](docs/MCP_TOOLS.md)** lists MCP tool names, JSON-schema-style inputs, and the **tool → replayt** mapping table. **[docs/MISSION.md § First replayt-backed tool calling](docs/MISSION.md#first-replayt-backed-tool-calling-e2e-milestone)** states refined acceptance criteria for the smallest replayt-backed path and tests.

**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** describes process boundaries, layering, tool groups, and how this repo stays a thin consumer of replayt.

## Security, secrets, and MCP hosting

**[docs/SECURITY.md](docs/SECURITY.md)** lists environment variables that affect the bridge and replayt, **what must never be logged** (tokens, PII, raw tool arguments), recommended **local stdio vs remote** deployment patterns, and how **replayt credentials** interact with this process. Read it before exposing the server beyond a trusted local MCP parent.


## Reference documentation (optional)

[`docs/reference-documentation/`](docs/reference-documentation/) may include **attributed** snapshots of upstream replayt
docs (from PyPI sdists) for offline reading. They do **not** replace this repo’s own contract docs ([`docs/MCP_TOOLS.md`](docs/MCP_TOOLS.md), etc.).
To refresh snapshots after changing the supported replayt range, run `python scripts/refresh_replayt_reference_docs.py` from the repo root (see the reference README for details).

## Quick start

**MCP hosts:** configure your client for **stdio** and run either the **`replayt-mcp-bridge`** console script (from `[project.scripts]` in `pyproject.toml`) or **`python -m replayt_mcp_bridge`** after install; both speak MCP over stdin/stdout. See **[Integrator recipes](#integrator-recipes)** for copy-paste host JSON and [docs/MISSION.md#mcp-server-stdio](docs/MISSION.md#mcp-server-stdio) for the full spec and acceptance notes.

**Security:** Any MCP client attached to the process can invoke registered tools; stdio is controlled by the parent process, so run the bridge only in environments where that boundary matches your policy. See [Security, secrets, and MCP hosting](#security-secrets-and-mcp-hosting) and [Security and trust boundaries](docs/MISSION.md#security-and-trust-boundaries).

**Logging:** On startup the bridge configures the `replayt_mcp_bridge` logger at **`INFO`** by default and writes **JSON lines** to stderr (`event`, `tool`, optional `mcp_request_id`, `status`, …). Set **`REPLAYT_MCP_BRIDGE_LOG_LEVEL`** to another stdlib level name (e.g. `DEBUG` or `WARNING`) to tune verbosity. See [docs/SECURITY.md](docs/SECURITY.md) for redaction rules and MCP host logging risks.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Editable install pulls replayt (see pyproject.toml) and pytest; add [dev] for ruff.
pip install -U pip
pip install -e .
# Optional: pip install -e ".[dev]"  # includes ruff
```

On **Windows**, if `pip install -e .` fails with `WinError 2` while updating `replayt.exe` under `Scripts\`, you usually have a **mixed user-site and system** install or a half-removed script. Use the venv above (so everything installs under `.venv\`) or repair/remove the broken `replayt` install and invalid `~…` folders pip warns about under `Lib\site-packages`.

## Integrator recipes

Copy-paste **stdio** MCP host configuration for **Claude Desktop** (`mcpServers`), **Cursor** (`.cursor/mcp.json` with **`type: "stdio"`**), and **Zed** (`context_servers`)—including **`command` / `args`**, **`cwd`** or workspace notes, and **generic** path placeholders (no real secrets)—is in **[docs/MCP_HOST_CONFIG.md](docs/MCP_HOST_CONFIG.md)**. Examples use the same canonical entrypoints as this README: **`replayt-mcp-bridge`** and **`python -m replayt_mcp_bridge`**.

## Local checks (pytest and Ruff)

After `pip install -e ".[dev]"` in your venv (Ruff is in the `dev` extra; pytest is included by the base editable install):

```bash
ruff check src tests
ruff format --check src tests
pytest -q
```

CI runs the same steps; see [.github/workflows/ci.yml](.github/workflows/ci.yml) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Optional agent workflows

This repo may include a [`.cursor/skills/`](.cursor/skills/) directory for Cursor-style agent skills. Adapt or remove it to
match your team’s tooling.

## Project layout

| Path | Purpose |
| ---- | ------- |
| `CHANGELOG.md` | Release history (Keep a Changelog) |
| `CONTRIBUTING.md` | How to run checks locally and what CI enforces |
| `.github/workflows/ci.yml` | Automated Ruff + pytest workflow |
| `docs/REPLAYT_ECOSYSTEM_IDEA.md` | Positioning (core-gap / showcase / bridge / combinator prompts) |
| `docs/MISSION.md` | Mission and scope |
| `docs/DESIGN_PRINCIPLES.md` | Design and integration principles |
| `docs/MCP_HOST_CONFIG.md` | MCP host JSON / stdio launch examples (Claude Desktop, Cursor, Zed) |
| `docs/MCP_TOOLS.md` | MCP tool catalog and mapping to replayt APIs / CLI |
| `docs/ARCHITECTURE.md` | Bridge layering, stdio process model, and review notes |
| `docs/REPLAYT_0_5_COMPATIBILITY_SPIKE.md` | Maintainer spike log for replayt 0.5.x compatibility (procedure + findings) |
| `docs/SECURITY.md` | Env vars, logging rules, deployment trust boundary, replayt credentials |
| `docs/reference-documentation/` | Optional markdown snapshot for contributors (when present) |
| `src/replayt_mcp_bridge/` | Python package (import `replayt_mcp_bridge`) |
| `pyproject.toml` | Package metadata |
