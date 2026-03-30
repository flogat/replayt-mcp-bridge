"""Shared utilities for the MCP bridge."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Awaitable, Callable, TypeVar

from replayt_mcp_bridge.observability import (
    emit_json_log,
    maybe_redact_tool_error_message_for_mcp,
    resolve_bridge_tool_timeout_seconds,
)
from replayt_mcp_bridge.tools_common import _tool_invocation_correlation_id

T = TypeVar("T")

# Match structured tool boundary logs (tools_common).
logger = logging.getLogger("replayt_mcp_bridge.server")


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
        "message": maybe_redact_tool_error_message_for_mcp(message),
        "correlation_id": correlation_id,
        **extra,
    }


def with_timeout(
    func: Callable[..., Awaitable[T]], tool_name: str
) -> Callable[..., Awaitable[T]]:
    """Wrap an async handler with bridge ``asyncio.wait_for`` using ``resolve_bridge_tool_timeout_seconds``."""

    async def wrapper(*args: Any, **kwargs: Any) -> T:
        timeout_seconds, timeout_source = resolve_bridge_tool_timeout_seconds(tool_name)
        if timeout_seconds is None:
            return await func(*args, **kwargs)
        try:
            return await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            cid = _correlation_id_for_timeout_payload()
            emit_json_log(
                logger,
                logging.ERROR,
                "replayt_mcp_bridge.tool.timeout",
                tool=tool_name,
                correlation_id=cid,
                timeout_seconds=timeout_seconds,
                timeout_source=timeout_source,
            )
            return _tool_error(
                tool=tool_name,
                replayt_surface="bridge_timeout",
                message="Tool execution timed out",
                correlation_id=cid,
                timeout_seconds=timeout_seconds,
                timeout_source=timeout_source,
            )

    return wrapper
