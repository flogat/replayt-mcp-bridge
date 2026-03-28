"""Shared FastMCP application object (stdio server registration target)."""

from __future__ import annotations

import logging
from typing import Any, Sequence

from mcp.server.fastmcp import FastMCP
from mcp.types import ContentBlock, Tool as MCPTool

from replayt_mcp_bridge.observability import (
    DISABLE_DIAGNOSTIC_ECHO_TOOLS_ENV,
    GATED_DIAGNOSTIC_ECHO_TOOL_NAMES_V1,
    diagnostic_echo_tools_disabled,
    emit_json_log,
)
from replayt_mcp_bridge.tools_common import (
    _correlation_id_for_invocation,
    _tool_error,
    _tool_invocation_correlation_id,
    logger,
)


class BridgeFastMCP(FastMCP):
    """FastMCP subclass that filters gated diagnostic echo tools when the env gate is on."""

    async def list_tools(self) -> list[MCPTool]:
        tools = await super().list_tools()
        if not diagnostic_echo_tools_disabled():
            return tools
        return [t for t in tools if t.name not in GATED_DIAGNOSTIC_ECHO_TOOL_NAMES_V1]

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        if (
            diagnostic_echo_tools_disabled()
            and name in GATED_DIAGNOSTIC_ECHO_TOOL_NAMES_V1
        ):
            context = self.get_context()
            correlation_id = _correlation_id_for_invocation(context)
            log_fields: dict[str, Any] = {"correlation_id": correlation_id}
            if context is not None:
                try:
                    log_fields["mcp_request_id"] = context.request_id
                except ValueError:
                    pass
            token = _tool_invocation_correlation_id.set(correlation_id)
            try:
                emit_json_log(
                    logger,
                    logging.INFO,
                    "replayt_mcp_bridge.tool.begin",
                    tool=name,
                    **log_fields,
                )
                out = _tool_error(
                    tool=name,
                    replayt_surface="bridge_diagnostic_tools_disabled",
                    message=(
                        "Diagnostic echo tools are disabled by operator configuration "
                        f"({DISABLE_DIAGNOSTIC_ECHO_TOOLS_ENV})."
                    ),
                )
                emit_json_log(
                    logger,
                    logging.INFO,
                    "replayt_mcp_bridge.tool.end",
                    tool=name,
                    status="error",
                    **log_fields,
                )
                return out
            finally:
                _tool_invocation_correlation_id.reset(token)
        return await super().call_tool(name, arguments)


mcp = BridgeFastMCP("replayt-mcp-bridge")
