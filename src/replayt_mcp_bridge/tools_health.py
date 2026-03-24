"""MCP tools: wiring / health (echo, version)."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp.server import Context

from replayt_mcp_bridge import (
    installed_replayt_version,
    installed_replayt_version_tuple,
)
from replayt_mcp_bridge.mcp_instance import mcp
from replayt_mcp_bridge.tools_common import _log_replayt_tool_boundaries


@mcp.tool()
@_log_replayt_tool_boundaries
def replayt_echo(message: str, ctx: Context | None = None) -> dict[str, Any]:
    """Echo a string back to the client to verify MCP tool invocation and stdio wiring."""

    return {"status": "ok", "echo": message}


@mcp.tool()
@_log_replayt_tool_boundaries
def replayt_version_info(ctx: Context | None = None) -> dict[str, Any]:
    """Report installed replayt and bridge versions (PEP 440 string and replayt's version tuple)."""

    major, minor, patch = installed_replayt_version_tuple()
    return {
        "status": "ok",
        "replayt_version": installed_replayt_version(),
        "replayt_version_tuple": {"major": major, "minor": minor, "patch": patch},
        "bridge_package": "replayt-mcp-bridge",
    }
