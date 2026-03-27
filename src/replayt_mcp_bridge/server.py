"""Minimal MCP server (stdio) for replayt-mcp-bridge."""

from __future__ import annotations

import logging

from replayt_mcp_bridge.observability import configure_bridge_logging, emit_json_log
from replayt_mcp_bridge.mcp_instance import mcp

# Register FastMCP tool handlers (import side effects).
from replayt_mcp_bridge import tools_health  # noqa: F401
from replayt_mcp_bridge import tools_persistence  # noqa: F401
from replayt_mcp_bridge import tools_workflow  # noqa: F401

logger = logging.getLogger(__name__)


def run_stdio() -> None:
    """Run the MCP server on stdin/stdout (JSON-RPC per MCP)."""

    configure_bridge_logging()
    emit_json_log(
        logger, logging.INFO, "replayt_mcp_bridge.server.start", transport="stdio"
    )
    mcp.run(transport="stdio")
