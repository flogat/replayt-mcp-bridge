"""Shared utilities for the MCP bridge."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Awaitable, Callable, TypeVar

from replayt_mcp_bridge.observability import get_tool_timeout_seconds
from replayt_mcp_bridge.tools_common import _tool_invocation_correlation_id

T = TypeVar("T")

# Shared logger instance for the bridge
logger = logging.getLogger("replayt_mcp_bridge")


def _correlation_id_for_timeout_payload() -> str:
    """Use the active tool correlation id when inside ``_log_replayt_tool_boundaries``; else a new UUID."""

    cid = _tool_invocation_correlation_id.get()
    if cid is not None:
        return cid
    return str(uuid.uuid4())


def _tool_error(
    tool: str,
    replayt_surface: str,
    message: str,
    correlation_id: str,
    **extra: Any,
) -> dict[str, Any]:
    """Construct a standardized error response for MCP tool results."""
    return {
        "status": "error",
        "tool": tool,
        "replayt_surface": replayt_surface,
        "message": message,
        "correlation_id": correlation_id,
        **extra,
    }


def with_timeout(
    func: Callable[..., Awaitable[T]], tool_name: str
) -> Callable[..., Awaitable[T]]:
    """
    Wrap an async handler to enforce a timeout based on the environment variable.

    Returns the original function if the env var is unset or invalid.
    """
    timeout_seconds = get_tool_timeout_seconds()

    async def wrapper(*args: Any, **kwargs: Any) -> T:
        if timeout_seconds is None:
            return await func(*args, **kwargs)
        try:
            return await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            cid = _correlation_id_for_timeout_payload()
            logger.error(
                "Tool execution timed out",
                extra={
                    "tool": tool_name,
                    "correlation_id": cid,
                    "timeout_seconds": timeout_seconds,
                    "event": "replayt_mcp_bridge.tool.timeout",
                },
            )
            return _tool_error(
                tool=tool_name,
                replayt_surface="bridge_timeout",
                message="Tool execution timed out",
                correlation_id=cid,
            )

    return wrapper
