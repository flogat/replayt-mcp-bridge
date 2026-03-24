"""Minimal MCP server (stdio) for replayt-mcp-bridge."""

from __future__ import annotations

import logging

from replayt_mcp_bridge.mcp_instance import mcp
from replayt_mcp_bridge.observability import configure_bridge_logging, emit_json_log

# Register FastMCP tool handlers (import side effects).
from replayt_mcp_bridge import tools_health  # noqa: F401
from replayt_mcp_bridge import tools_persistence  # noqa: F401
from replayt_mcp_bridge import tools_workflow  # noqa: F401
from replayt_mcp_bridge.persistence_support import _split_typed_store_hint
from replayt_mcp_bridge.tools_health import replayt_echo, replayt_version_info
from replayt_mcp_bridge.tools_persistence import persistence_list_run_events
from replayt_mcp_bridge.tools_workflow import (
    runner_dry_run_plan,
    workflow_contract_snapshot,
    workflow_graph_mermaid,
)

logger = logging.getLogger(__name__)

__all__ = [
    "_split_typed_store_hint",
    "persistence_list_run_events",
    "replayt_echo",
    "replayt_version_info",
    "runner_dry_run_plan",
    "run_stdio",
    "workflow_contract_snapshot",
    "workflow_graph_mermaid",
]


def run_stdio() -> None:
    """Run the MCP server on stdin/stdout (JSON-RPC per MCP)."""

    configure_bridge_logging()
    emit_json_log(
        logger, logging.INFO, "replayt_mcp_bridge.server.start", transport="stdio"
    )
    mcp.run(transport="stdio")
