# Architecture: replayt-mcp-bridge

This document summarizes how the bridge is structured after the initial MCP tool surface is implemented in-process against replayt. It complements [MISSION.md](MISSION.md) (scope and trust boundaries) and [MCP_TOOLS.md](MCP_TOOLS.md) (tool catalog and schemas).

## Process and transport

- **Entry:** `python -m replayt_mcp_bridge` or the `replayt-mcp-bridge` console script → `replayt_mcp_bridge.__main__` → `server.run_stdio()`.
- **Transport:** [FastMCP](https://github.com/modelcontextprotocol/python-sdk) (`mcp.server.fastmcp`) with **`transport="stdio"`**. MCP clients speak JSON-RPC over the process stdin/stdout pair; the bridge does not open network listeners in this mode.
- **Single module of behavior:** Tool handlers and small helpers live in **`src/replayt_mcp_bridge/server.py`**. There is no separate “adapter layer” package yet; keeping one file preserves a clear boundary until the surface grows.

## Layering (conceptual)

```text
MCP host (IDE, agent runtime, CLI wrapper)
        │ JSON-RPC / MCP tool calls
        ▼
FastMCP (schema from Python signatures, stdio framing)
        │
        ▼
replayt_mcp_bridge.server  — validate/locate paths, map errors to JSON
        │
        ▼
replayt public APIs  — load_target, Workflow.contract, graph export,
                        validation_report, JSONLStore / SQLiteStore
```

**Rule:** Workflow semantics and persistence formats are **owned by replayt**. This repo owns **tool names**, **argument normalization**, **JSON-safe result shapes**, and **documented mapping** from each tool to a replayt surface.

## Tool groups

| Group | Tools | Role |
| ----- | ----- | ---- |
| Wiring / health | `replayt_echo`, `replayt_version_info` | Prove MCP wiring and report the resolved replayt version (integrator diagnostics). |
| Workflow introspection | `workflow_contract_snapshot`, `workflow_graph_mermaid` | Resolve a CLI-style **target** and expose contract and Mermaid graph text without running steps. |
| Runner (dry) | `runner_dry_run_plan` | Graph validation plus `validation_report` aligned with `replayt run --dry-check`; optional `inputs_json` string. |
| Persistence read | `persistence_list_run_events` | Read-only access to events via JSONL log directory or SQLite path; default log dir matches CLI resolution when `store_hint` is omitted. |

## Shared implementation patterns

- **Structured errors:** Operational failures that should reach the client as data use `_tool_error(...)` → `{ status: "error", tool, replayt_surface, message }`. `typer.BadParameter` from `load_target` and invalid run IDs are mapped this way instead of leaking stack traces across the MCP boundary.
- **Persistence resolution:** `_resolve_persistence_paths` interprets `store_hint` (default dir, JSONL directory, or `.sqlite`/`.db` file). `_open_read_store` yields a read-only store for `load_events`.
- **Schema stability:** Tool inputs are plain Python parameters on `@mcp.tool()` functions; hosts receive JSON Schema derived by FastMCP. Prefer additive optional parameters over breaking renames.

## Non-goals (architecture)

- **Vendoring replayt** or reimplementing workflow execution here.
- **Implicit network or subprocess tool calls** beyond what replayt’s imported APIs already do when loading targets or stores.
- **Large generic “run arbitrary replayt CLI” tools** without explicit contracts—new tools should map to documented replayt capabilities like the mapping table in [MCP_TOOLS.md](MCP_TOOLS.md).

## Review notes (risks and follow-ups)

- **Parity:** `runner_dry_run_plan` currently fixes `strict_graph=False` and omits optional JSON blobs that the CLI may accept; exposing them as optional MCP parameters is a backward-compatible extension.
- **Persistence hints:** Path/suffix heuristics work for JSONL dirs vs SQLite files; a structured `store_hint` (e.g. typed URI prefixes) would be a separate, explicit contract change.
- **Event privacy:** Returned events are replayt’s stored JSON as-is; any redaction policy belongs in docs and optional bridge-level filtering if integrators require it.

### Security review (phase 6)

- **Transport:** Documented path remains **stdio-only** for the bridge entrypoint; attack surface is whoever can attach to that process’s stdin/stdout (parent MCP host).
- **Implementation:** `server.py` uses **no** `subprocess` or shell for tool dispatch; inputs are passed into replayt APIs and `pathlib` helpers. Residual risk is **upstream** (what `load_target`, validation, and stores do when given adversarial-but-valid strings).
- **Information disclosure:** Structured `_tool_error` responses carry **string messages** only (often from `typer.BadParameter` or `OSError`), which may include paths or hints useful to integrators but also to a malicious client on the same machine—keep MCP attachment within policy. **Unhandled exceptions** are not converted to `_tool_error` today; behavior depends on FastMCP / host error handling (documented in [MISSION.md](MISSION.md#security-and-trust-boundaries)).
- **Follow-ups:** Optional hardening includes catching unexpected exceptions and returning a generic error (with logging server-side), allowlisting `store_hint` roots if deployers need it, and event redaction or field filtering if policies require it.

## Related files

| Path | Purpose |
| ---- | ------- |
| `src/replayt_mcp_bridge/server.py` | FastMCP app, tool implementations, persistence helpers |
| `src/replayt_mcp_bridge/__main__.py` | Stdio server entry |
| `docs/MCP_TOOLS.md` | Tool → replayt mapping and input shapes |
| `tests/test_mcp_tools.py` | Contract tests at the replayt boundary |
