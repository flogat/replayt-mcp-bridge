"""Minimal MCP server (stdio) for replayt-mcp-bridge."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextvars import ContextVar
from typing import Any, Callable, Coroutine, TypeVar

from mcp.server.fastmcp import FastMCP

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

T = TypeVar("T")
R = TypeVar("R")

# Global context var for correlation ID
_correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")

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


def get_tool_timeout_seconds() -> float | None:
    """Get the tool execution timeout from environment, in seconds."""
    val = os.environ.get("REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_SECONDS")
    if not val:
        return None
    try:
        seconds = float(val)
        if seconds <= 0:
            logger.warning(
                "REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_SECONDS must be positive, got %s; ignoring",
                val,
            )
            return None
        return seconds
    except ValueError:
        logger.warning(
            "Invalid REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_SECONDS value: %s; ignoring",
            val,
        )
        return None


def _correlation_id_for_invocation() -> str:
    """Generate or retrieve a correlation ID for the current invocation."""
    cid = _correlation_id_var.get()
    if not cid:
        cid = str(uuid.uuid4())
        _correlation_id_var.set(cid)
    return cid


def _tool_error(
    tool: str,
    replayt_surface: str,
    message: str,
    status: str = "error",
) -> dict[str, Any]:
    """Return a structured error object for MCP tool results."""
    cid = _correlation_id_for_invocation()
    return {
        "status": status,
        "tool": tool,
        "replayt_surface": replayt_surface,
        "message": message,
        "correlation_id": cid,
    }


def _timeout_error(tool: str) -> dict[str, Any]:
    """Return a structured timeout error."""
    return _tool_error(
        tool=tool,
        replayt_surface="bridge_timeout",
        message="Tool execution timed out",
    )


def with_timeout(
    func: Callable[..., Coroutine[Any, Any, R]],
    tool_name: str,
) -> Callable[..., Coroutine[Any, Any, R]]:
    """Wrap an async tool handler with a timeout."""
    timeout_seconds = get_tool_timeout_seconds()

    async def wrapper(*args: Any, **kwargs: Any) -> R:
        if timeout_seconds is None:
            return await func(*args, **kwargs)
        try:
            return await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            # Log the timeout event
            cid = _correlation_id_for_invocation()
            emit_json_log(
                logger,
                logging.WARNING,
                "replayt_mcp_bridge.tool.timeout",
                correlation_id=cid,
                tool=tool_name,
                timeout_seconds=timeout_seconds,
            )
            # Return structured error (will be serialized by FastMCP)
            return _timeout_error(tool_name)  # type: ignore[return-value]

    return wrapper


# Create the FastMCP instance
mcp = FastMCP("replayt-bridge")


def run_stdio() -> None:
    """Run the MCP server on stdin/stdout (JSON-RPC per MCP)."""

    configure_bridge_logging()
    emit_json_log(
        logger, logging.INFO, "replayt_mcp_bridge.server.start", transport="stdio"
    )
    mcp.run(transport="stdio")
