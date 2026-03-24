# MCP tools (initial surface)

This bridge exposes a small, versioned set of MCP tools that map to **replayt** APIs or CLI workflows. **Input schemas stay stable** so clients can integrate early; workflow, dry-check, and persistence tools call replayt in-process (see `src/replayt_mcp_bridge/server.py`). For process boundaries and how tools sit above replayt, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Mapping: tool → replayt capability

| MCP tool | Replayt / CLI surface | Notes |
| -------- | ---------------------- | ----- |
| `replayt_echo` | _(bridge only)_ | Proves MCP wiring; echoes input. |
| `replayt_version_info` | `replayt.__version__` / `replayt.__version_tuple__` | Reads installed replayt via the same helpers as `replayt_mcp_bridge.installed_replayt_version`. |
| `workflow_contract_snapshot` | `Workflow.contract()`, via `replayt.cli.targets.load_target` | Same **target** grammar as `replayt contract` / `replayt run` (e.g. `module.path:wf`, `workflow.py`). Returns `{ status, target, contract }` or `{ status: error, tool, replayt_surface, message }`. |
| `workflow_graph_mermaid` | `replayt.graph_export.workflow_to_mermaid` | Aligns with `replayt graph` Mermaid output. Returns `{ status, target, mermaid }` or an error object. |
| `runner_dry_run_plan` | `replayt run --dry-check` (graph validation + `validation_report`) | Validates graph and optional JSON strings without executing steps or writing logs. Returns `{ status: ok \| invalid, report }` matching `replayt.validate_report.v1`, or an error object. Optional `strict_graph` and `metadata_json` / `experiment_json` / `policy_hook_context_json` match the CLI `--dry-check` knobs; defaults and gaps are documented under [Dry-check parity specification (runner_dry_run_plan)](#dry-check-parity-specification-runner_dry_run_plan). |
| `persistence_list_run_events` | `EventStore.load_events` on JSONL log dir or SQLite DB | `store_hint`: omit for project-resolved default log dir (`resolve_log_dir(DEFAULT_LOG_DIR)`), or pass a JSONL **directory** path, or a `.sqlite` / `.db` file. Optional env **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** (see [SECURITY.md](SECURITY.md)) restricts **explicit** `store_hint` paths to resolved locations under listed absolute roots. Returns `{ status, run_id, event_count, events, store }` or an error object. |

## Input shapes (JSON Schema concepts)

Tools are registered with the official Python MCP SDK (`mcp.server.fastmcp`); hosts receive JSON Schema derived from the Python signatures below.

### `replayt_echo`

| Property | Type | Required |
| -------- | ---- | -------- |
| `message` | string | yes |

### `replayt_version_info`

No properties (empty object).

### `workflow_contract_snapshot`

| Property | Type | Required |
| -------- | ---- | -------- |
| `target` | string | yes |

### `workflow_graph_mermaid`

| Property | Type | Required |
| -------- | ---- | -------- |
| `target` | string | yes |

### `runner_dry_run_plan`

| Property | Type | Required |
| -------- | ---- | -------- |
| `target` | string | yes |
| `inputs_json` | string \| null | no (JSON object text for the `inputs` slot in `replayt.cli.validation.validation_report`, when present) |
| `strict_graph` | boolean | no (default `false`; same as `validate_workflow_graph` / `validation_report` and CLI `--strict-graph`) |
| `metadata_json` | string \| null | no (JSON object text for `validation_report` `metadata_json`; default `null`) |
| `experiment_json` | string \| null | no (JSON object text for `validation_report` `experiment_json`; default `null`) |
| `policy_hook_context_json` | string \| null | no (JSON object text for `validation_report` `policy_hook_context_json`; default `null`) |

### Dry-check parity specification (runner_dry_run_plan)

This section refines **what “CLI parity” means** between the MCP tool and **`replayt run … --dry-check`** for integrators. It is derived from the **public Python entrypoints** the bridge calls (`replayt.cli.validation.validate_workflow_graph`, `validation_report`) and from **`replayt run … --dry-check`** in `replayt.cli.commands.run` within the declared **`replayt>=0.4.25,<0.5`** range.

**Handler behavior:** `runner_dry_run_plan` loads the target, runs `validate_workflow_graph(wf, strict_graph=…)`, then `validation_report` with the same `strict_graph`, `inputs_json`, `metadata_json`, `experiment_json`, and `policy_hook_context_json` values supplied by the client (omitted parameters use the defaults below, matching CLI defaults: `--strict-graph` off, optional JSON flags omitted).

**Target contract (additive MCP parameters only):** Each optional argument can be omitted; omission preserves the same defaults as before these parameters existed.

| MCP parameter | replayt API | `replayt run --dry-check` CLI |
| ------------- | ----------- | ------------------------------ |
| `strict_graph` (boolean, default `false`) | Same value passed to `validate_workflow_graph` and `validation_report` | `--strict-graph` |
| `metadata_json` (string \| null, default null) | `validation_report(..., metadata_json=…)` | `--metadata-json` |
| `experiment_json` (string \| null, default null) | `validation_report(..., experiment_json=…)` | `--experiment-json` |
| `policy_hook_context_json` (string \| null, default null) | `validation_report(..., policy_hook_context_json=…)` | `--policy-hook-context-json` (CLI may parse `@path` / `@-`; MCP hosts typically pass inline JSON object text) |

**Semantics:** Each `*_json` parameter is **JSON object text** (or `null`). Malformed or non-object JSON is surfaced as `status: "invalid"` via replayt’s report `errors` list (same pattern as `inputs_json` today). The bridge continues **not** to implement CLI-only ergonomics such as `@path` indirection or stdin reads for those strings unless explicitly specified later.

**Input resolution gap (documented, out of scope for this parity item):** The CLI merges `--inputs-json`, `--inputs-file`, repeatable `--input`, and project/env defaults through `resolve_run_inputs_json` before calling `validation_report`. The MCP tool exposes a **single** optional `inputs_json` string aligned with the **`inputs_json`** argument to `validation_report`, not the full CLI resolution stack. Closing that gap would require a **documented public helper** from replayt (or a deliberate bridge policy), not ad hoc duplication of CLI resolution.

**Backlog closure checks:**

1. `runner_dry_run_plan` exposes the four optional parameters with defaults matching prior hard-coded behavior (`strict_graph=false`, other JSON parameters `null`).
2. This document’s mapping row, input shapes table, and security table reflect the handler surface.
3. Pytest covers **at least one** knob that changes the outcome versus the default (`strict_graph=true` on a **trusted** two-state workflow file with no declared transitions; packaged `replayt_examples` targets in the supported range currently include transitions, so the contract test uses an on-disk `.py` workflow under `tmp_path`, same resolution path as `load_target` for files).

### `persistence_list_run_events`

| Property | Type | Required |
| -------- | ---- | -------- |
| `run_id` | string | yes |
| `store_hint` | string \| null | no (optional store URI or path hint for multi-backend setups) |

## Error response shape

Target loading, persistence validation, and store resolution failures return a JSON object with **`status: "error"`** and operational fields (no Python traceback in the structured content for the **mapped** paths listed below).

### Current payload (released)

```json
{
  "status": "error",
  "tool": "<tool_name>",
  "replayt_surface": "<short mapping label>",
  "message": "…"
}
```

### Specification: `correlation_id` (bounded structured errors backlog)

**Goal:** MCP client authors can quote a single identifier when reporting issues; operators find the same value in **structured stderr logs** for that tool invocation—without putting tracebacks in the tool result.

| Requirement | Detail |
| ----------- | ------ |
| **Tool result** | Every mapped operational error (same rows as [Mapped failure paths](#mapped-failure-paths-exception--branch-inventory)) **MUST** include a string field **`correlation_id`**. |
| **Stderr logs** | Every structured JSON log line emitted by the bridge for that **same invocation** (at minimum `replayt_mcp_bridge.tool.begin`, `replayt_mcp_bridge.tool.end`, `replayt_mcp_bridge.tool.unhandled_exception` when applicable, and bridge events such as `replayt_mcp_bridge.store_hint.rejected` that occur inside a tool handler) **MUST** include the **same** **`correlation_id`** value. |
| **Value** | If FastMCP exposes a non-empty `Context.request_id` for the call, **`correlation_id` MUST** reuse that string. Otherwise the bridge **MUST** generate a new UUID (version 4) once per tool entry and reuse it until the handler returns or raises. |

**Implementation status:** The current code path returns the four-field object above and logs optional **`mcp_request_id`** on boundaries when the SDK provides it; **`correlation_id`** on tool results and in logs is **not yet implemented**—this subsection is the integrator contract for that work.

### Mapped failure paths (exception / branch inventory)

These are the **only** bridge-recognized routes to `{ "status": "error", … }` today. After `correlation_id` ships, each row’s errors **MUST** carry the field per the table above.

| MCP tool(s) | Trigger | Mechanism | Typical `replayt_surface` (handler) |
| ----------- | ------- | --------- | ------------------------------------- |
| `workflow_contract_snapshot` | Bad or unresolvable **target** | `typer.BadParameter` from `replayt.cli.targets.load_target` → `_tool_error` | `Workflow.contract + replayt.cli.targets.load_target` |
| `workflow_graph_mermaid` | Bad **target** | same | `replayt.graph_export.workflow_to_mermaid` |
| `runner_dry_run_plan` | Bad **target** | same (`load_target` before validation) | `replayt run --dry-check / validate_workflow_graph + validation_report` |
| `persistence_list_run_events` | Invalid **run_id** | `ValueError` from `replayt.persistence.jsonl.validate_run_id` → `_tool_error` | `EventStore.load_events (JSONL directory or SQLite file)` |
| `persistence_list_run_events` | **store_hint** points at a plain file that is not SQLite | `_resolve_persistence_paths` returns an error string → `_tool_error` | same |
| `persistence_list_run_events` | Explicit **store_hint** rejected by **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** | branch → `_tool_error` (+ optional `replayt_mcp_bridge.store_hint.rejected` log) | same |
| `persistence_list_run_events` | SQLite path does not exist or is not a file | branch → `_tool_error` | same |
| `persistence_list_run_events` | Store open / read failure | `OSError` from `_open_read_store` / `load_events` → `_tool_error` | same |

**Outside `status: "error"`:** `runner_dry_run_plan` graph/input validation failures use **`status: "invalid"`** and a `replayt.validate_report.v1` object in **`report`** (replayt-owned semantics).

### Unmapped exceptions (explicit)

Any **other** exception raised while executing a tool (for example an unexpected `RuntimeError` from replayt after `load_target` succeeds) is **not** converted to `{ "status": "error", … }`. The bridge logs `replayt_mcp_bridge.tool.unhandled_exception` (and a traceback via `logger.exception`), then **re-raises**; presentation to MCP clients depends on FastMCP / host behavior. **Tests** should keep at least one path where unmapped failures remain observable (e.g. handler tests that assert propagation or host-visible errors when the suite deliberately provokes them); do not widen `except Exception` without updating this table and adding focused tests.

## Success and validation shapes (MCP structured content)

Handlers return plain dicts that the MCP SDK serializes as structured tool content:

- **`status: "ok"`** — Normal completion (`replayt_echo`, `replayt_version_info`, successful contract/graph/persistence reads).
- **`status: "invalid"`** — Used only by `runner_dry_run_plan` when the graph/inputs fail validation; the `report` field is a `replayt.validate_report.v1` object (same schema replayt uses for `--dry-check` style output).
- **`status: "error"`** — Expected operational failures (bad target, bad `run_id`, missing store, I/O errors) using the error object above—not a substitute for MCP transport errors; **unhandled** exceptions may still propagate per SDK/host behavior. When the [correlation identifier specification](#specification-correlation_id-bounded-structured-errors-backlog) is implemented, mapped errors will also include **`correlation_id`**, mirrored in stderr logs.

For the **first end-to-end replayt milestone** (import + optional target resolution), see [MISSION.md § First replayt-backed tool calling](MISSION.md#first-replayt-backed-tool-calling-e2e-milestone).

## Security

Tools that load workflow definitions or read event stores follow the **same trust model as running replayt locally** (see [MISSION.md](MISSION.md#security-and-trust-boundaries)). Concretely for this surface:

| Tool | Filesystem / code | Notes |
| ---- | ----------------- | ----- |
| `replayt_echo` | None | Reflected string only; harmless technically, but hosts should not treat echoed content as trusted if it is fed back into models or UIs. |
| `replayt_version_info` | None | Reads package metadata only. |
| `workflow_contract_snapshot` | **Yes** (via `load_target`) | Can import modules and read workflow files the server user can access—equivalent to `replayt contract` target resolution. |
| `workflow_graph_mermaid` | **Yes** (same as above) | Same target resolution as contract snapshot. |
| `runner_dry_run_plan` | **Yes** (target + optional JSON strings: `inputs_json`, `metadata_json`, `experiment_json`, `policy_hook_context_json`, and `strict_graph`) | Same trust model as passing those flags to `replayt run --dry-check`: resolves the target, validates graph/text only; no workflow execution or log writes. |
| `persistence_list_run_events` | **Yes** (`store_hint`, default log dir) | Read-only store access; returns raw stored events (no redaction). Operators may set **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** so explicit `store_hint` values outside configured roots are rejected with a structured error (default log-dir resolution when `store_hint` is omitted is unchanged). |

The bridge does **not** add shell indirection for these parameters. **Operators** should assume any connected MCP client can invoke all registered tools with arbitrary arguments permitted by the schemas.

**Operator guidance:** Required environment variables, “do not log” expectations, deployment patterns (local stdio vs shared host), and MCP host logging risks are documented in [docs/SECURITY.md](SECURITY.md).

**Error payloads:** Structured `{ status: error, tool, replayt_surface, message }` responses may include filesystem paths or other operational detail in `message` (e.g. from `typer.BadParameter`, I/O errors). Treat them as visible to every attached client unless you filter at the host. Bridge stderr logs are JSON lines with tool name, optional MCP request id, and result status—not full MCP arguments—with redaction for sensitive-shaped keys (see [ARCHITECTURE.md § Observability](ARCHITECTURE.md#observability)). After **`correlation_id`** is implemented (see [Error response shape](#error-response-shape)), operators can align client-reported ids with the same field in those logs. Deeper review notes live under [ARCHITECTURE.md § Security review (phase 6)](ARCHITECTURE.md#security-review-phase-6).
