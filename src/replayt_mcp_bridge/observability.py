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
