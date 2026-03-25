# Changelog

...

## [Unreleased]

### Added

- **Execution timeouts for replayt-backed handlers** — Added optional `REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_SECONDS` environment variable to enforce per-tool timeouts. When a tool exceeds the timeout, the bridge returns a structured error (`status: "error"`, `replayt_surface: "bridge_timeout"`) and logs a `replayt_mcp_bridge.tool.timeout` event. Documented in `docs/MCP_TOOLS.md` and `docs/SECURITY.md`. [Backlog: Define and enforce per-tool execution timeouts for replayt-backed handlers]

...
