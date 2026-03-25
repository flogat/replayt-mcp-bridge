# Security: secrets, environment, and trust boundaries

...

## Environment variables

...

| Variable | Role |
| -------- | ---- |
| `REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_SECONDS` | **Optional timeout** for tool execution. When set to a positive number (e.g., `30`), the bridge enforces a timeout on each tool call. If a tool exceeds this duration, it returns a structured error (`status: "error"`, `replayt_surface: "bridge_timeout"`) and logs a `replayt_mcp_bridge.tool.timeout` event. Default: no timeout (unlimited). |

...
