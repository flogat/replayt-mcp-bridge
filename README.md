# MCP tool bridge for replayt workflow steps

**[docs/MISSION.md](docs/MISSION.md)** — scope, non-goals, success criteria, and how this repo relates to upstream replayt.

**[CONTRIBUTING.md](CONTRIBUTING.md)** — local **pytest** / **Ruff** commands and PR expectations (aligned with CI).

## Overview

This project builds on **[replayt](https://pypi.org/project/replayt/)**. Use
**[docs/REPLAYT_ECOSYSTEM_IDEA.md](docs/REPLAYT_ECOSYSTEM_IDEA.md)** for positioning context and the chosen primary pattern.

## Design principles

**[docs/DESIGN_PRINCIPLES.md](docs/DESIGN_PRINCIPLES.md)** covers **replayt** compatibility, versioning, and (for showcases)
**LLM** boundaries.

**[docs/MCP_TOOLS.md](docs/MCP_TOOLS.md)** lists MCP tool names, JSON-schema-style inputs, and the **tool → replayt** mapping table. **[docs/MISSION.md § First replayt-backed tool calling](docs/MISSION.md#first-replayt-backed-tool-calling-e2e-milestone)** states refined acceptance criteria for the smallest replayt-backed path and tests.

**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** describes process boundaries, layering, tool groups, and how this repo stays a thin consumer of replayt.


## Reference documentation (optional)

This checkout does not yet include [`docs/reference-documentation/`](docs/reference-documentation/). You can add markdown
copies of upstream replayt documentation there for offline review or agent context.

## Quick start

**MCP hosts:** configure your client for **stdio** and run either the **`replayt-mcp-bridge`** console script (from `[project.scripts]` in `pyproject.toml`) or **`python -m replayt_mcp_bridge`** after install; both speak MCP over stdin/stdout. See [docs/MISSION.md#mcp-server-stdio](docs/MISSION.md#mcp-server-stdio) for the full spec and acceptance notes.

**Security:** Any MCP client attached to the process can invoke registered tools; stdio is controlled by the parent process, so run the bridge only in environments where that boundary matches your policy. See [Security and trust boundaries](docs/MISSION.md#security-and-trust-boundaries) in the mission doc.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Editable install pulls replayt (see pyproject.toml) and pytest; add [dev] for ruff.
pip install -U pip
pip install -e .
# Optional: pip install -e ".[dev]"  # includes ruff
```

On **Windows**, if `pip install -e .` fails with `WinError 2` while updating `replayt.exe` under `Scripts\`, you usually have a **mixed user-site and system** install or a half-removed script. Use the venv above (so everything installs under `.venv\`) or repair/remove the broken `replayt` install and invalid `~…` folders pip warns about under `Lib\site-packages`.

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
| `CONTRIBUTING.md` | How to run checks locally and what CI enforces |
| `.github/workflows/ci.yml` | Automated Ruff + pytest workflow |
| `docs/REPLAYT_ECOSYSTEM_IDEA.md` | Positioning (core-gap / showcase / bridge / combinator prompts) |
| `docs/MISSION.md` | Mission and scope |
| `docs/DESIGN_PRINCIPLES.md` | Design and integration principles |
| `docs/MCP_TOOLS.md` | MCP tool catalog and mapping to replayt APIs / CLI |
| `docs/ARCHITECTURE.md` | Bridge layering, stdio process model, and review notes |
| `docs/reference-documentation/` | Optional markdown snapshot for contributors (when present) |
| `src/replayt_mcp_bridge/` | Python package (import `replayt_mcp_bridge`) |
| `pyproject.toml` | Package metadata |
