# MCP tool bridge for replayt workflow steps

**[docs/MISSION.md](docs/MISSION.md)** — scope, non-goals, success criteria, and how this repo relates to upstream replayt.

## Overview

This project builds on **[replayt](https://pypi.org/project/replayt/)**. Use
**[docs/REPLAYT_ECOSYSTEM_IDEA.md](docs/REPLAYT_ECOSYSTEM_IDEA.md)** for positioning context and the chosen primary pattern.

## Design principles

**[docs/DESIGN_PRINCIPLES.md](docs/DESIGN_PRINCIPLES.md)** covers **replayt** compatibility, versioning, and (for showcases)
**LLM** boundaries.


## Reference documentation (optional)

This checkout does not yet include [`docs/reference-documentation/`](docs/reference-documentation/). You can add markdown
copies of upstream replayt documentation there for offline review or agent context.

## Quick start

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
```

## Optional agent workflows

This repo may include a [`.cursor/skills/`](.cursor/skills/) directory for Cursor-style agent skills. Adapt or remove it to
match your team’s tooling.

## Project layout

| Path | Purpose |
| ---- | ------- |
| `docs/REPLAYT_ECOSYSTEM_IDEA.md` | Positioning (core-gap / showcase / bridge / combinator prompts) |
| `docs/MISSION.md` | Mission and scope |
| `docs/DESIGN_PRINCIPLES.md` | Design and integration principles |
| `docs/reference-documentation/` | Optional markdown snapshot for contributors (when present) |
| `src/replayt_mcp_bridge/` | Python package (import `replayt_mcp_bridge`) |
| `pyproject.toml` | Package metadata |
