"""Structured stdlib logging, optional MCP correlation fields, and redaction helpers."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
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
