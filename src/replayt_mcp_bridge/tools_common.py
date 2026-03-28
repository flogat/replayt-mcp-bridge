"""Shared tool decorator, correlation IDs, and structured error helper."""

from __future__ import annotations

import contextvars
import functools
import inspect
import logging
import uuid
from typing import Any, Callable, TypeVar

from mcp.server.fastmcp.utilities.context_injection import find_context_parameter

from replayt_mcp_bridge.observability import (
    emit_json_log,
    maybe_redact_tool_error_message_for_mcp,
)

# Preserve pre-split logger namespace so stderr JSON and caplog tests stay aligned.
logger = logging.getLogger("replayt_mcp_bridge.server")

F = TypeVar("F", bound=Callable[..., dict[str, Any]])

_tool_invocation_correlation_id: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar(
        "replayt_mcp_bridge_tool_invocation_correlation_id", default=None
    )
)


def _correlation_id_for_invocation(ctx: Any) -> str:
    """Prefer FastMCP ``Context.request_id`` when non-empty; else a new UUID4 (per MCP_TOOLS)."""

    if ctx is not None:
        try:
            rid = str(ctx.request_id).strip()
            if rid:
                return rid
        except (ValueError, AttributeError):
            pass
    return str(uuid.uuid4())


def _active_tool_correlation_id() -> str:
    """Correlation id for the current tool handler (set by ``_log_replayt_tool_boundaries``)."""

    cid = _tool_invocation_correlation_id.get()
    if cid is None:
        raise RuntimeError("replayt_mcp_bridge internal: tool correlation_id not set")
    return cid


def _log_replayt_tool_boundaries(fn: F) -> F:
    """Log tool name, correlation id, optional MCP request id, and outcome status."""

    name = fn.__name__
    ctx_kw = find_context_parameter(fn)

    def _corr_from_kwargs(kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any], Any]:
        ctx = kwargs.get(ctx_kw) if ctx_kw else None
        correlation_id = _correlation_id_for_invocation(ctx)
        corr: dict[str, Any] = {"correlation_id": correlation_id}
        if ctx is not None:
            try:
                corr["mcp_request_id"] = ctx.request_id
            except ValueError:
                pass
        return ctx, corr, _tool_invocation_correlation_id.set(correlation_id)

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def wrapped_async(*args: Any, **kwargs: Any) -> dict[str, Any]:
            _ctx, corr, reset_token = _corr_from_kwargs(kwargs)
            try:
                emit_json_log(
                    logger,
                    logging.INFO,
                    "replayt_mcp_bridge.tool.begin",
                    tool=name,
                    **corr,
                )
                try:
                    out = await fn(*args, **kwargs)
                except Exception:
                    emit_json_log(
                        logger,
                        logging.ERROR,
                        "replayt_mcp_bridge.tool.unhandled_exception",
                        tool=name,
                        **corr,
                    )
                    logger.exception(
                        "replayt_mcp_bridge.tool.unhandled_exception_trace"
                    )
                    raise
                status = out.get("status") if isinstance(out, dict) else None
                emit_json_log(
                    logger,
                    logging.INFO,
                    "replayt_mcp_bridge.tool.end",
                    tool=name,
                    status=status,
                    **corr,
                )
                return out
            finally:
                _tool_invocation_correlation_id.reset(reset_token)

        return wrapped_async  # type: ignore[return-value]

    @functools.wraps(fn)
    def wrapped_sync(*args: Any, **kwargs: Any) -> dict[str, Any]:
        _ctx, corr, reset_token = _corr_from_kwargs(kwargs)
        try:
            emit_json_log(
                logger, logging.INFO, "replayt_mcp_bridge.tool.begin", tool=name, **corr
            )
            try:
                out = fn(*args, **kwargs)
            except Exception:
                emit_json_log(
                    logger,
                    logging.ERROR,
                    "replayt_mcp_bridge.tool.unhandled_exception",
                    tool=name,
                    **corr,
                )
                logger.exception("replayt_mcp_bridge.tool.unhandled_exception_trace")
                raise
            status = out.get("status") if isinstance(out, dict) else None
            emit_json_log(
                logger,
                logging.INFO,
                "replayt_mcp_bridge.tool.end",
                tool=name,
                status=status,
                **corr,
            )
            return out
        finally:
            _tool_invocation_correlation_id.reset(reset_token)

    return wrapped_sync  # type: ignore[return-value]


def _tool_error(*, tool: str, replayt_surface: str, message: str) -> dict[str, Any]:
    cid = _tool_invocation_correlation_id.get()
    out: dict[str, Any] = {
        "status": "error",
        "tool": tool,
        "replayt_surface": replayt_surface,
        "message": maybe_redact_tool_error_message_for_mcp(message),
    }
    if cid is not None:
        out["correlation_id"] = cid
    return out
