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

## Observability

- **Server lifecycle:** `run_stdio()` logs `replayt_mcp_bridge.server.start` with `transport: stdio` once before blocking on the MCP run loop.
- **Replayt-backed tools:** `_log_replayt_tool_boundaries` logs `replayt_mcp_bridge.tool.begin` (tool name only) and `replayt_mcp_bridge.tool.end` (tool name plus result `status`). Client argument values are omitted on purpose so logs stay usable without copying MCP payloads verbatim.
- **Unhandled exceptions:** After `logger.exception` with `replayt_mcp_bridge.tool.unhandled_exception`, the exception propagates; FastMCP / host behavior applies (see [MISSION.md](MISSION.md#security-and-trust-boundaries)).
- **Bridge-only tools:** `replayt_echo` is not wrapped—there is no replayt boundary to mark at the handler level.

## Non-goals (architecture)

- **Vendoring replayt** or reimplementing workflow execution here.
- **Implicit network or subprocess tool calls** beyond what replayt’s imported APIs already do when loading targets or stores.
- **Large generic “run arbitrary replayt CLI” tools** without explicit contracts—new tools should map to documented replayt capabilities like the mapping table in [MCP_TOOLS.md](MCP_TOOLS.md).

## CI and contributor automation

**Source of truth:** [.github/workflows/ci.yml](../.github/workflows/ci.yml) installs with `pip install -e ".[dev]"`, then runs **`ruff check`**, **`ruff format --check`**, and **`pytest -q`** as **separate steps** so the first failure is obvious. Pip cache uses `actions/setup-python` with `cache-dependency-path: pyproject.toml`. The workflow sets **`permissions: contents: read`** so the default `GITHUB_TOKEN` cannot write repository contents. The matrix covers Python **3.11** and **3.12**; the **`replayt-floor`** job reinstalls **`replayt==0.4.25`** after the editable install to guard the declared lower bound in `pyproject.toml`.

**Documentation mirror:** [README.md](../README.md) (“Local checks”) and [CONTRIBUTING.md](../CONTRIBUTING.md) list the same Ruff and pytest invocations so contributors can reproduce CI without a shared script—duplication is intentional so each doc stands alone.

**Backlog alignment:** The “pytest + ruff CI + CONTRIBUTING expectations” item is structurally satisfied: workflow on PR/push (plus `mc/**` pushes), README and CONTRIBUTING document local commands and `pip install -e ".[dev]"` for Ruff, and [MISSION.md](MISSION.md#ci-and-contributor-automation) records the refined acceptance criteria. **Default branch green** remains an operational outcome after merge.

## Review notes (risks and follow-ups)

- **Phase 5 (architecture review):** Confirmed layering, error mapping, and trust boundaries in this doc and [MCP_TOOLS.md](MCP_TOOLS.md) match `server.py`; E2E milestone tools (`replayt_version_info`, `workflow_contract_snapshot`, etc.) align with [MISSION.md](MISSION.md#first-replayt-backed-tool-calling-e2e-milestone). [CI and contributor automation](#ci-and-contributor-automation) above records how CI, README, CONTRIBUTING, and mission criteria fit together for the backlog item. Remaining gaps are product choices (strict staging of “milestone 1” vs expanded surface, generic catch-all errors), not structural contradictions.
- **Phase 6 (security review):** `server.py` was reviewed against [MISSION.md](MISSION.md#security-and-trust-boundaries) and the [MCP_TOOLS.md](MCP_TOOLS.md) security table; findings are summarized in [Security review (phase 6)](#security-review-phase-6) below. No handler changes were required for the stated stdio / trusted-operator model; CI gained explicit read-only `contents` permissions; optional hardenings remain follow-ups.
- **Parity:** `runner_dry_run_plan` currently fixes `strict_graph=False` and omits optional JSON blobs that the CLI may accept; exposing them as optional MCP parameters is a backward-compatible extension.
- **Persistence hints:** Path/suffix heuristics work for JSONL dirs vs SQLite files; a structured `store_hint` (e.g. typed URI prefixes) would be a separate, explicit contract change.
- **Event privacy:** Returned events are replayt’s stored JSON as-is; any redaction policy belongs in docs and optional bridge-level filtering if integrators require it.

### Security review (phase 6)

**Scope:** Line-by-line review of `src/replayt_mcp_bridge/server.py` against [MISSION.md](MISSION.md#security-and-trust-boundaries) and the security table in [MCP_TOOLS.md](MCP_TOOLS.md).

**Transport and process:** The documented entrypath remains **stdio-only**; the bridge does not open its own network listeners. Whoever controls the parent process (or can substitute stdio) can invoke tools—treat MCP attachment as a **trusted-operator** boundary, not anonymous wide-area exposure.

**Dispatch path:** Tool handlers call replayt APIs and `pathlib` helpers only. There is **no** `subprocess`, `os.system`, or shell string assembly for MCP arguments.

| Input / surface | Bridge handling | Residual risk |
| --------------- | --------------- | ------------- |
| `target` | Passed to `load_target` | Same as the replayt CLI: **Python import** and **workflow file reads** for resources the server user can access. |
| `inputs_json` (`runner_dry_run_plan`) | Passed to `validation_report` after graph validation | Malformed JSON is reported as `status: "invalid"` via replayt’s validation report (not a bridge-level exception in spot checks). Other unexpected replayt exceptions remain possible and follow the unhandled path below. |
| `store_hint` | `expanduser`, `Path.resolve(strict=False)`, then read-only `JSONLStore` / `SQLiteStore` | Any path the OS allows the process to open; **symlinks** resolve per platform rules. Plain files that are not SQLite are rejected with `_tool_error`. |
| `run_id` | `validate_run_id_for_store` before `load_events` | Identifier validation only; **event payloads** are returned as stored (no bridge redaction). |
| `replayt_echo(message)` | Returned in the structured result | **Reflection** if echoed content is fed into models or UIs; bridge-only, **not** wrapped by `_log_replayt_tool_boundaries`. |

**Information disclosure:** `_tool_error` returns string `message` fields (from `typer.BadParameter`, `ValueError`, `OSError`, or hint validation). Those strings may include paths or operational detail useful to integrators and visible to **any** connected MCP client—scope who may attach. **Unhandled** exceptions are logged with `replayt_mcp_bridge.tool.unhandled_exception` and then propagate; presentation to clients depends on FastMCP / host behavior (see [MISSION.md](MISSION.md#security-and-trust-boundaries)).

**Logging:** Replayt-backed tools log tool name and result `status` at begin/end only—**no** client argument values in those records.

**Follow-ups (product / optional hardening):** Catch a narrow set of unexpected exceptions and return a generic structured error (with correlation id); allowlist `store_hint` roots for multi-tenant deploys; optional event field redaction; stricter documentation staging if integrators want a “milestone 1 only” tool exposure story.

## Related files

| Path | Purpose |
| ---- | ------- |
| `.github/workflows/ci.yml` | Ruff + pytest workflow and replayt floor job |
| `CONTRIBUTING.md` | Local check commands aligned with CI |
| `src/replayt_mcp_bridge/server.py` | FastMCP app, tool implementations, persistence helpers |
| `src/replayt_mcp_bridge/__main__.py` | Stdio server entry |
| `docs/MCP_TOOLS.md` | Tool → replayt mapping and input shapes |
| `tests/test_mcp_tools.py` | Contract tests at the replayt boundary |
