"""Structured stdlib logging, optional MCP correlation fields, and redaction helpers."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_BRIDGE_LOG_LEVEL = logging.INFO

# Bridge wall-clock limit for replayt-backed MCP tools when no valid env override applies.
DEFAULT_BRIDGE_TOOL_TIMEOUT_SECONDS = 300.0

_GLOBAL_TOOL_TIMEOUT_ENV = "REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_SECONDS"

# Substrings matched case-insensitively against dict keys (and list/tuple indices are not keyed — see redact_structure).
_SENSITIVE_KEY_MARKERS: tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "auth",
    "bearer",
    "credential",
    "cookie",
    "private_key",
    "access_key",
)


def _is_sensitive_key(name: str) -> bool:
    lower = name.lower().replace("-", "_")
    return any(m in lower for m in _SENSITIVE_KEY_MARKERS)


def redact_structure(value: Any) -> Any:
    """Return a copy of JSON-like structures with sensitive-key leaves redacted."""

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if _is_sensitive_key(str(k)):
                out[str(k)] = None if v is None else "[REDACTED]"
            else:
                out[str(k)] = redact_structure(v)
        return out
    if isinstance(value, list):
        return [redact_structure(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_structure(v) for v in value)
    return value


def emit_json_log(
    logger: logging.Logger, level: int, event: str, **fields: Any
) -> None:
    """Emit one JSON object per log line (message body only; handler uses %(message)s)."""

    safe = redact_structure(dict(fields))
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "level": logging.getLevelName(level),
        "event": event,
        **safe,
    }
    logger.log(level, json.dumps(payload, separators=(",", ":"), default=str))


def resolve_log_level_from_env() -> int:
    """Read ``REPLAYT_MCP_BRIDGE_LOG_LEVEL`` (default INFO). See docs/SECURITY.md."""

    raw = os.environ.get("REPLAYT_MCP_BRIDGE_LOG_LEVEL", "INFO").strip().upper()
    return getattr(logging, raw, DEFAULT_BRIDGE_LOG_LEVEL)


def _per_tool_timeout_env_name(tool_name: str) -> str:
    """Env key for ``REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_<TOOL>_SECONDS`` (``<TOOL>`` uppercased)."""

    return f"REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_{tool_name.upper()}_SECONDS"


def _parse_timeout_seconds(
    log: logging.Logger, env_name: str, raw: str
) -> float | None:
    """Parse a timeout env value. Returns ``None`` if empty/invalid. Non-positive values are valid parses."""

    stripped = raw.strip()
    if not stripped:
        log.warning(
            "Invalid %s value: empty; ignoring at this precedence step", env_name
        )
        return None
    try:
        return float(stripped)
    except ValueError:
        log.warning(
            "Invalid %s value: %s; ignoring at this precedence step", env_name, raw
        )
        return None


def resolve_bridge_tool_timeout_seconds(tool_name: str) -> tuple[float | None, str]:
    """Resolve the effective bridge ``wait_for`` limit for ``tool_name``.

    Precedence (see docs/MCP_TOOLS.md): per-tool env → global env → built-in **300** s.
    Returns ``(None, source)`` when the winning value is ``≤ 0`` (bridge timeout disabled).
    ``source`` is ``per_tool_env``, ``global_env``, or ``default`` when the limit is positive;
    when disabled via a parsed env value, ``source`` is ``per_tool_env`` or ``global_env``.
    """

    log = logging.getLogger("replayt_mcp_bridge")
    per_name = _per_tool_timeout_env_name(tool_name)
    if per_name in os.environ:
        parsed = _parse_timeout_seconds(log, per_name, os.environ[per_name])
        if parsed is not None:
            if parsed > 0:
                return (parsed, "per_tool_env")
            return (None, "per_tool_env")

    if _GLOBAL_TOOL_TIMEOUT_ENV in os.environ:
        parsed = _parse_timeout_seconds(
            log, _GLOBAL_TOOL_TIMEOUT_ENV, os.environ[_GLOBAL_TOOL_TIMEOUT_ENV]
        )
        if parsed is not None:
            if parsed > 0:
                return (parsed, "global_env")
            return (None, "global_env")

    return (DEFAULT_BRIDGE_TOOL_TIMEOUT_SECONDS, "default")


_RUN_EVENTS_REDACTION_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes", "on"})


def run_events_redaction_enabled() -> bool:
    """Return whether ``persistence_list_run_events`` should redact sensitive-shaped keys in returned events.

    Reads ``REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS``. When **unset**, empty, or any value other than a case-insensitive
    match for **1**, **true**, **yes**, or **on**, redaction is **off** (pass-through, no extra structure copies).
    """

    raw = os.environ.get("REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS")
    if raw is None:
        return False
    return raw.strip().lower() in _RUN_EVENTS_REDACTION_TRUTHY


def parse_default_run_event_field_allowlist() -> list[str] | None:
    """Parse ``REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`` for ``persistence_list_run_events``.

    Comma-separated **top-level** JSON object keys (trimmed; empty segments ignored). Returns ``None`` when unset,
    whitespace-only, or no usable names after parsing—meaning **no** default field allowlist (full event objects).
    Duplicate names are deduplicated in first-seen order.
    """

    raw = os.environ.get("REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS")
    if raw is None:
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return None
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def parse_store_hint_allowlist_roots() -> list[Path] | None:
    """Parse ``REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`` for ``persistence_list_run_events``.

    Returns:
        ``None`` — allowlist not configured; explicit ``store_hint`` paths are not restricted by
        this feature (normal validation still applies).
        ``[]`` — the variable was set to a non-empty value but no usable absolute roots were
        parsed; explicit ``store_hint`` is rejected.
        Non-empty list — each path is a resolved absolute root; the resolved store path must be
        equal to or under one of them (``Path.is_relative_to``).
    """

    raw = os.environ.get("REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS")
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    roots: list[Path] = []
    seen: set[str] = set()
    for part in stripped.split(","):
        seg = part.strip()
        if not seg:
            continue
        try:
            r = Path(seg).expanduser().resolve(strict=False)
        except (OSError, RuntimeError):
            continue
        if not r.is_absolute():
            continue
        key = os.path.normcase(str(r))
        if key not in seen:
            seen.add(key)
            roots.append(r)
    return roots


def configure_bridge_logging() -> None:
    """Attach a stderr handler with message-only formatting for ``replayt_mcp_bridge``."""

    level = resolve_log_level_from_env()
    root = logging.getLogger("replayt_mcp_bridge")
    root.setLevel(level)
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    root.propagate = False
