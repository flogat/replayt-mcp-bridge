"""MCP tools: read-only persistence (run events)."""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server.fastmcp.server import Context
from replayt import LogLockError
from replayt.persistence.jsonl import validate_run_id as validate_run_id_for_store

from replayt_mcp_bridge.mcp_instance import mcp
from replayt_mcp_bridge.tools_bounds import EventFieldsOpt, RunIdStr, TierAStringOpt
from replayt_mcp_bridge.observability import (
    emit_json_log,
    parse_default_run_events_max_count,
    parse_default_run_events_max_total_bytes,
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
    run_id: RunIdStr,
    store_hint: TierAStringOpt = None,
    event_fields: EventFieldsOpt = None,
    max_events: int | None = None,
    max_total_bytes: int | None = None,
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
        max_events,
        max_total_bytes,
        ctx,
    )


def _run_events_compact_json_utf8_len(events: list[Any]) -> int:
    return len(
        json.dumps(events, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


async def _persistence_list_run_events_impl(
    run_id: RunIdStr,
    store_hint: TierAStringOpt,
    event_fields: EventFieldsOpt,
    max_events: int | None,
    max_total_bytes: int | None,
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
    if max_events is not None and max_events <= 0:
        return _tool_error(
            tool=tool,
            replayt_surface=surface,
            message=(
                "max_events must be omitted, null, or a positive integer "
                "(use REPLAYT_MCP_BRIDGE_RUN_EVENTS_MAX_COUNT=0 to disable the count cap for the process)."
            ),
        )
    if max_total_bytes is not None and max_total_bytes <= 0:
        return _tool_error(
            tool=tool,
            replayt_surface=surface,
            message=(
                "max_total_bytes must be omitted, null, or a positive integer "
                "(use REPLAYT_MCP_BRIDGE_RUN_EVENTS_MAX_TOTAL_BYTES=0 to disable the byte cap for the process)."
            ),
        )
    try:
        with _open_read_store(log_dir, sqlite) as store:
            events = store.load_events(safe_run_id)
    except LogLockError as exc:
        return _tool_error(
            tool=tool,
            replayt_surface="replayt.persistence.jsonl (JSONL log lock)",
            message=str(exc),
        )
    except OSError as exc:
        return _tool_error(tool=tool, replayt_surface=surface, message=str(exc))

    eff_max_events = (
        max_events if max_events is not None else parse_default_run_events_max_count()
    )
    eff_max_bytes = (
        max_total_bytes
        if max_total_bytes is not None
        else parse_default_run_events_max_total_bytes()
    )
    volume_surface = "bridge_run_events_volume"
    n_events = len(events)
    if eff_max_events is not None and n_events > eff_max_events:
        emit_json_log(
            logger,
            logging.WARNING,
            "replayt_mcp_bridge.run_events.volume_limit",
            reason="event_count",
            correlation_id=_active_tool_correlation_id(),
            observed_event_count=n_events,
            limit_event_count=eff_max_events,
        )
        return _tool_error(
            tool=tool,
            replayt_surface=volume_surface,
            message=(
                f"Run events exceed the configured event count limit: "
                f"observed {n_events} events, limit {eff_max_events}."
            ),
        )
    if eff_max_bytes is not None:
        encoded_len = _run_events_compact_json_utf8_len(events)
        if encoded_len > eff_max_bytes:
            emit_json_log(
                logger,
                logging.WARNING,
                "replayt_mcp_bridge.run_events.volume_limit",
                reason="encoded_size",
                correlation_id=_active_tool_correlation_id(),
                observed_encoded_utf8_bytes=encoded_len,
                limit_total_bytes=eff_max_bytes,
            )
            return _tool_error(
                tool=tool,
                replayt_surface=volume_surface,
                message=(
                    f"Run events exceed the configured encoded size limit: "
                    f"observed {encoded_len} UTF-8 bytes (compact JSON of the loaded list), "
                    f"limit {eff_max_bytes}."
                ),
            )

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
