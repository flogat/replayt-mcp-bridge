# MCP tools (initial surface)

This bridge exposes a small, versioned set of MCP tools that map to **replayt** APIs or CLI workflows. **Input schemas stay stable** so clients can integrate early; workflow, dry-check, and persistence tools call replayt in-process (handlers in `src/replayt_mcp_bridge/tools_*.py`, registered when `server.py` imports those modules). For process boundaries and how tools sit above replayt, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Execution timeouts

To prevent long-running replayt work from blocking the MCP stdio session, the bridge enforces a configurable timeout on tool execution.

- **Configuration**: Set the environment variable `REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_SECONDS` to a positive number (e.g., `30` for 30 seconds).
- **Default**: No timeout (unlimited) if the variable is unset or invalid.
- **Behavior**: When a tool execution exceeds the timeout, the bridge returns a structured error with `status: "error"`, `tool: "<tool_name>"`, `replayt_surface: "bridge_timeout"`, and `message: "Tool execution timed out"`. The same `correlation_id` is logged in stderr.
- **Scope**: Applies to all replayt-backed tools that can block (e.g., `workflow_contract_snapshot`, `runner_dry_run_plan`, `persistence_list_run_events`). Diagnostic tools like `replayt_echo` and `replayt_version_info` are exempt for performance.

**Example**:
```bash
export REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_SECONDS=60
python -m replayt_mcp_bridge
```

## Mapping: tool → replayt capability

...

## Input shapes (JSON Schema concepts)

...

## Error response shape

...

### Mapped failure paths (exception / branch inventory)

...

| MCP tool(s) | Trigger | Mechanism | Typical `replayt_surface` (handler) |
| ----------- | ------- | --------- | ------------------------------------- |
| All tools | Execution timeout | `asyncio.TimeoutError` caught by bridge wrapper | `bridge_timeout` |

...
