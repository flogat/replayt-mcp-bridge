# MCP tools (initial surface)

This bridge exposes a small, versioned set of MCP tools that map to **replayt** APIs or CLI workflows. **Input schemas stay stable** so clients can integrate early; workflow, dry-check, and persistence tools call replayt in-process (see `src/replayt_mcp_bridge/server.py`). For process boundaries and how tools sit above replayt, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Mapping: tool → replayt capability

| MCP tool | Replayt / CLI surface | Notes |
| -------- | ---------------------- | ----- |
| `replayt_echo` | _(bridge only)_ | Proves MCP wiring; echoes input. |
| `replayt_version_info` | `replayt.__version__` / `replayt.__version_tuple__` | Reads installed replayt via the same helpers as `replayt_mcp_bridge.installed_replayt_version`. |
| `workflow_contract_snapshot` | `Workflow.contract()`, via `replayt.cli.targets.load_target` | Same **target** grammar as `replayt contract` / `replayt run` (e.g. `module.path:wf`, `workflow.py`). Returns `{ status, target, contract }` or `{ status: error, tool, replayt_surface, message }`. |
| `workflow_graph_mermaid` | `replayt.graph_export.workflow_to_mermaid` | Aligns with `replayt graph` Mermaid output. Returns `{ status, target, mermaid }` or an error object. |
| `runner_dry_run_plan` | `replayt run --dry-check` (graph validation + `validation_report`) | Validates graph and optional JSON strings without executing steps or writing logs. Returns `{ status: ok \| invalid, report }` matching `replayt.validate_report.v1`, or an error object. **Planned optional knobs** (not all exposed on the handler yet) are specified under [Dry-check parity specification (runner_dry_run_plan)](#dry-check-parity-specification-runner_dry_run_plan). |
| `persistence_list_run_events` | `EventStore.load_events` on JSONL log dir or SQLite DB | `store_hint`: omit for project-resolved default log dir (`resolve_log_dir(DEFAULT_LOG_DIR)`), or pass a JSONL **directory** path, or a `.sqlite` / `.db` file. Returns `{ status, run_id, event_count, events, store }` or an error object. |

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

### Dry-check parity specification (runner_dry_run_plan)

This section refines **what “CLI parity” means** between the MCP tool and **`replayt run … --dry-check`** for integrators and for a future implementation pass. It is derived from the **public Python entrypoints** the bridge already calls (`replayt.cli.validation.validate_workflow_graph`, `validation_report`) and from **`replayt run … --dry-check`** in `replayt.cli.commands.run` within the declared **`replayt>=0.4.25,<0.5`** range.

**Today (handler as shipped):** `runner_dry_run_plan` loads the target, runs `validate_workflow_graph(wf, strict_graph=False)`, then `validation_report(..., strict_graph=False, inputs_json=…, metadata_json=None, experiment_json=None, policy_hook_context_json=None)`. That matches the CLI defaults (`--strict-graph` off, optional JSON flags omitted) but **does not yet expose** the other optional `validation_report` strings or `strict_graph=True`.

**Target contract (additive MCP parameters only):** Each new argument is **optional**; omitting it must preserve **today’s** behavior.

| Planned MCP parameter | replayt API | `replayt run --dry-check` CLI |
| --------------------- | ----------- | ------------------------------ |
| `strict_graph` (boolean, default `false`) | Same value passed to `validate_workflow_graph` and `validation_report` | `--strict-graph` |
| `metadata_json` (string \| null, default null) | `validation_report(..., metadata_json=…)` | `--metadata-json` |
| `experiment_json` (string \| null, default null) | `validation_report(..., experiment_json=…)` | `--experiment-json` |
| `policy_hook_context_json` (string \| null, default null) | `validation_report(..., policy_hook_context_json=…)` | `--policy-hook-context-json` (CLI may parse `@path` / `@-`; MCP hosts typically pass inline JSON object text) |

**Semantics:** Each `*_json` parameter is **JSON object text** (or `null`). Malformed or non-object JSON is surfaced as `status: "invalid"` via replayt’s report `errors` list (same pattern as `inputs_json` today). The bridge continues **not** to implement CLI-only ergonomics such as `@path` indirection or stdin reads for those strings unless explicitly specified later.

**Input resolution gap (documented, out of scope for this parity item):** The CLI merges `--inputs-json`, `--inputs-file`, repeatable `--input`, and project/env defaults through `resolve_run_inputs_json` before calling `validation_report`. The MCP tool exposes a **single** optional `inputs_json` string aligned with the **`inputs_json`** argument to `validation_report`, not the full CLI resolution stack. Closing that gap would require a **documented public helper** from replayt (or a deliberate bridge policy), not ad hoc duplication of CLI resolution.

**Refined acceptance criteria (implementation / backlog closure):**

1. Extend `runner_dry_run_plan` with the four optional parameters above; defaults must match the current hard-coded behavior (`strict_graph=false`, other JSON parameters absent/`null`).
2. Update this document: mapping table row, input shapes table, and security table if new columns warrant a one-line note.
3. Add pytest coverage that proves **at least one** new knob changes the outcome versus the previous default (recommended: `strict_graph=true` on a packaged **`replayt_examples`** workflow with **two or more states and no declared transitions**, where replayt emits a strict-graph error while the default passes graph validation).

### `persistence_list_run_events`

| Property | Type | Required |
| -------- | ---- | -------- |
| `run_id` | string | yes |
| `store_hint` | string \| null | no (optional store URI or path hint for multi-backend setups) |

## Error response shape

Target loading and store resolution failures return:

```json
{
  "status": "error",
  "tool": "<tool_name>",
  "replayt_surface": "<short mapping label>",
  "message": "…"
}
```

## Success and validation shapes (MCP structured content)

Handlers return plain dicts that the MCP SDK serializes as structured tool content:

- **`status: "ok"`** — Normal completion (`replayt_echo`, `replayt_version_info`, successful contract/graph/persistence reads).
- **`status: "invalid"`** — Used only by `runner_dry_run_plan` when the graph/inputs fail validation; the `report` field is a `replayt.validate_report.v1` object (same schema replayt uses for `--dry-check` style output).
- **`status: "error"`** — Expected operational failures (bad target, bad `run_id`, missing store, I/O errors) using the error object above—not a substitute for MCP transport errors; **unhandled** exceptions may still propagate per SDK/host behavior.

For the **first end-to-end replayt milestone** (import + optional target resolution), see [MISSION.md § First replayt-backed tool calling](MISSION.md#first-replayt-backed-tool-calling-e2e-milestone).

## Security

Tools that load workflow definitions or read event stores follow the **same trust model as running replayt locally** (see [MISSION.md](MISSION.md#security-and-trust-boundaries)). Concretely for this surface:

| Tool | Filesystem / code | Notes |
| ---- | ----------------- | ----- |
| `replayt_echo` | None | Reflected string only; harmless technically, but hosts should not treat echoed content as trusted if it is fed back into models or UIs. |
| `replayt_version_info` | None | Reads package metadata only. |
| `workflow_contract_snapshot` | **Yes** (via `load_target`) | Can import modules and read workflow files the server user can access—equivalent to `replayt contract` target resolution. |
| `workflow_graph_mermaid` | **Yes** (same as above) | Same target resolution as contract snapshot. |
| `runner_dry_run_plan` | **Yes** (target + optional JSON strings: `inputs_json`, and when implemented `metadata_json`, `experiment_json`, `policy_hook_context_json`) | Same trust model as passing those flags to `replayt run --dry-check`: resolves the target, validates graph/text only; no workflow execution or log writes. |
| `persistence_list_run_events` | **Yes** (`store_hint`, default log dir) | Read-only store access; returns raw stored events (no redaction). |

The bridge does **not** add shell indirection for these parameters. **Operators** should assume any connected MCP client can invoke all registered tools with arbitrary arguments permitted by the schemas.

**Operator guidance:** Required environment variables, “do not log” expectations, deployment patterns (local stdio vs shared host), and MCP host logging risks are documented in [docs/SECURITY.md](SECURITY.md).

**Error payloads:** Structured `{ status: error, tool, replayt_surface, message }` responses may include filesystem paths or other operational detail in `message` (e.g. from `typer.BadParameter`, I/O errors). Treat them as visible to every attached client unless you filter at the host. Bridge stderr logs are JSON lines with tool name, optional MCP request id, and result status—not full MCP arguments—with redaction for sensitive-shaped keys (see [ARCHITECTURE.md § Observability](ARCHITECTURE.md#observability)). Deeper review notes live under [ARCHITECTURE.md § Security review (phase 6)](ARCHITECTURE.md#security-review-phase-6).
