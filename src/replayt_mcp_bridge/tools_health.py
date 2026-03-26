"""Health check tools."""

from __future__ import annotations

from typing import Any

from . import installed_replayt_version, installed_replayt_version_tuple
from .mcp_instance import mcp
from .tools_common import _log_replayt_tool_boundaries


@mcp.tool()
@_log_replayt_tool_boundaries
def replayt_echo(message: str) -> dict[str, str]:
    """Echo a message back to the client."""
    return {"status": "ok", "echo": message}


@mcp.tool()
@_log_replayt_tool_boundaries
def replayt_version_info() -> dict[str, Any]:
    """Return the installed replayt version."""
    major, minor, patch = installed_replayt_version_tuple()
    return {
        "status": "ok",
        "replayt_version": installed_replayt_version(),
        "replayt_version_tuple": {"major": major, "minor": minor, "patch": patch},
    }
