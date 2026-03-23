# MCP tools (initial surface)

This bridge exposes a small, versioned set of MCP tools that map to **replayt** APIs or CLI workflows. Implementations may be stubs that return a structured `not_implemented` payload until a later slice; **input schemas stay stable** so clients can integrate early.

## Mapping: tool → replayt capability

| MCP tool | Replayt / CLI surface | Notes |
| -------- | ---------------------- | ----- |
| `replayt_echo` | _(bridge only)_ | Proves MCP wiring; echoes input. |
| `replayt_version_info` | `replayt.__version__` / `replayt.__version_tuple__` | Reads installed replayt via the same helpers as `replayt_mcp_bridge.installed_replayt_version`. |
| `workflow_contract_snapshot` | `Workflow.contract()`, via `replayt.cli.targets.load_target` | Same **target** grammar as `replayt contract` / `replayt run` (e.g. `module.path:wf`, `workflow.py`). Stub until loader wiring is implemented in-process. |
| `workflow_graph_mermaid` | `replayt.graph_export.workflow_to_mermaid` | Aligns with `replayt graph` Mermaid output. Stub. |
| `runner_dry_run_plan` | `replayt run --dry-check` / `Runner` dry validation | Describes a future “validate workflow + inputs without side effects” bridge. Stub. |
| `persistence_list_run_events` | `EventStore.load_events`, `replayt runs` / inspect flows | Future bridge for reading JSONL-backed run timelines. Stub. |

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
| `inputs_json` | string \| null | no (JSON text of initial inputs when present) |

### `persistence_list_run_events`

| Property | Type | Required |
| -------- | ---- | -------- |
| `run_id` | string | yes |
| `store_hint` | string \| null | no (optional store URI or path hint for multi-backend setups) |

## Stub response shape

Stub tools return a JSON object of the form:

```json
{
  "status": "not_implemented",
  "tool": "<tool_name>",
  "replayt_surface": "<short mapping label>",
  "message": "…"
}
```

## Security

Tools that will load workflow code or read event stores (`target`-based tools, persistence) execute or read **only what the operator’s environment already allows**—same trust model as running `replayt run` locally. See [MISSION.md](MISSION.md#security-and-trust-boundaries).
