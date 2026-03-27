"""MCP tools: read-only persistence (run events)."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp.server import Context
from replayt.persistence.jsonl import validate_run_id as validate_run_id_for_store

from replayt_mcp_bridge.mcp_instance import mcp
from replayt_mcp_bridge.observability import (
    emit_json_log,
    parse_store_hint_allowlist_roots,
    redact_structure,
    run_events_redaction_enabled,
)
from replayt_mcp_bridge.persistence_support import (
    _filter_run_events_top_level_keys,
    _open_read_store,
    _path_allowed_under_store_hint_roots,
    _resolve_persistence_paths,
    _effective_run_event_field_allowlist,
)
from replayt_mcp_bridge.utils import with_timeout
from replayt_mcp_bridge.tools_common import (
    _active_tool_correlation_id,
    _log_replayt_tool_boundaries,
    _tool_error,
    logger,
)


@mcp.tool()
@_log_replayt_tool_boundaries
async def persistence_list_run_events(
    run_id: str,
    store_hint: str | None = None,
    event_fields: list[str] | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """List persisted events for a run_id (aligned with EventStore.load_events and `replayt runs` tooling)."""

    # Wrap the actual implementation with a timeout
    return await with_timeout(
        _persistence_list_run_events_impl,
        "persistence_list_run_events",
    )(
        run_id,
        store_hint,
        event_fields,
        ctx,
    )


async def _persistence_list_run_events_impl(
    run_id: str,
    store_hint: str | None,
    event_fields: list[str] | None,
    ctx: Context | None,
) -> dict[str, Any]:
    """Implementation of persistence_list_run_events (wrapped with timeout)."""
    tool = "persistence_list_run_events"
    surface = "EventStore.load_events (JSONL directory or SQLite file)"
    try:
        safe_run_id = validate_run_id_for_store(run_id)
    except ValueError as exc:
        return _tool_error(tool=tool, replayt_surface=surface, message=str(exc))
    log_dir, sqlite, hint_err = _resolve_persistence_paths(store_hint)
    if hint_err:
        return _tool_error(tool=tool, replayt_surface=surface, message=hint_err)
    allow_roots = parse_store_hint_allowlist_roots()
    if store_hint is not None and allow_roots is not None:
        if not allow_roots:
            emit_json_log(
                logger,
                logging.WARNING,
                "replayt_mcp_bridge.store_hint.rejected",
                reason="allowlist_unusable",
                correlation_id=_active_tool_correlation_id(),
            )
            return _tool_error(
                tool=tool,
                replayt_surface=surface,
                message=(
                    "REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS is set but no valid absolute "
                    "roots were parsed; refusing explicit store_hint."
                ),
            )
        store_path = sqlite if sqlite is not None else log_dir
        assert store_path is not None
        if not _path_allowed_under_store_hint_roots(store_path, allow_roots):
            emit_json_log(
                logger,
                logging.WARNING,
                "replayt_mcp_bridge.store_hint.rejected",
                reason="outside_allowlist",
                correlation_id=_active_tool_correlation_id(),
            )
            return _tool_error(
                tool=tool,
                replayt_surface=surface,
                message=(
                    "Store hint resolves outside REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS; "
                    "see docs/SECURITY.md."
                ),
            )
    if sqlite is not None and not sqlite.is_file():
        return _tool_error(
            tool=tool,
            replayt_surface=surface,
            message=f"SQLite store not found: {sqlite}",
        )
    try:
        with _open_read_store(log_dir, sqlite) as store:
            events = store.load_events(safe_run_id)
    except OSError as exc:
        return _tool_error(tool=tool, replayt_surface=surface, message=str(exc))
    allow = _effective_run_event_field_allowlist(event_fields)
    if allow:
        events_for_client = _filter_run_events_top_level_keys(events, allow)
    else:
        events_for_client = events
    if run_events_redaction_enabled():
        events_for_client = redact_structure(events_for_client)
    store_kind = "sqlite" if sqlite is not None else "jsonl"
    store_path = str(sqlite) if sqlite is not None else str(log_dir)
    return {
        "status": "ok",
        "run_id": safe_run_id,
        "event_count": len(events),
        "events": events_for_client,
        "store": {"kind": store_kind, "path": store_path},
    }
