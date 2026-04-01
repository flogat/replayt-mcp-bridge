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

DISABLE_DIAGNOSTIC_ECHO_TOOLS_ENV = "REPLAYT_MCP_BRIDGE_DISABLE_DIAGNOSTIC_ECHO_TOOLS"

# v1 gated MCP tool names; extend only with doc + test updates (see MCP_TOOLS.md).
GATED_DIAGNOSTIC_ECHO_TOOL_NAMES_V1: frozenset[str] = frozenset({"replayt_echo"})


def diagnostic_echo_tools_disabled() -> bool:
    """True when ``REPLAYT_MCP_BRIDGE_DISABLE_DIAGNOSTIC_ECHO_TOOLS`` is a redaction-style truthy token."""

    raw = os.environ.get(DISABLE_DIAGNOSTIC_ECHO_TOOLS_ENV)
    if raw is None:
        return False
    return raw.strip().lower() in _RUN_EVENTS_REDACTION_TRUTHY


def set_disable_diagnostic_echo_tools_for_cli() -> None:
    """Set the env var so the stdio server omits gated diagnostic echo tools (CLI flag only; see SECURITY.md)."""

    os.environ[DISABLE_DIAGNOSTIC_ECHO_TOOLS_ENV] = "1"


def run_events_redaction_enabled() -> bool:
    """Return whether ``persistence_list_run_events`` should redact sensitive-shaped keys in returned events.

    Reads ``REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS``. When **unset**, empty, or any value other than a case-insensitive
    match for **1**, **true**, **yes**, or **on**, redaction is **off** (pass-through, no extra structure copies).
    """

    raw = os.environ.get("REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS")
    if raw is None:
        return False
    return raw.strip().lower() in _RUN_EVENTS_REDACTION_TRUTHY


def maybe_redact_tool_error_message_for_mcp(message: str) -> str:
    """Return the string used for structured tool-error ``message`` fields sent to MCP clients.

    Default is **verbatim** passthrough so automated clients stay backward compatible. An opt-in
    ``REPLAYT_MCP_BRIDGE_*`` control for truncation or redaction may be layered here when specified
    in SECURITY.md / MCP_TOOLS.md (see **Structured error messages: paths and operational detail**).
    """

    return message


_DEFAULT_RUN_EVENTS_MAX_COUNT = 10_000
_DEFAULT_RUN_EVENTS_MAX_TOTAL_BYTES = 33_554_432  # 32 MiB

_RUN_EVENTS_MAX_COUNT_ENV = "REPLAYT_MCP_BRIDGE_RUN_EVENTS_MAX_COUNT"
_RUN_EVENTS_MAX_TOTAL_BYTES_ENV = "REPLAYT_MCP_BRIDGE_RUN_EVENTS_MAX_TOTAL_BYTES"


def parse_default_run_events_max_count() -> int | None:
    """Parse ``REPLAYT_MCP_BRIDGE_RUN_EVENTS_MAX_COUNT`` for ``persistence_list_run_events``.

    Returns ``None`` when the count cap is disabled (env **0** or negative). When unset, empty, or invalid, returns the
    built-in default **10_000**. When set to a positive integer, returns that limit.
    """

    log = logging.getLogger("replayt_mcp_bridge")
    raw = os.environ.get(_RUN_EVENTS_MAX_COUNT_ENV)
    if raw is None:
        return _DEFAULT_RUN_EVENTS_MAX_COUNT
    stripped = raw.strip()
    if not stripped:
        return _DEFAULT_RUN_EVENTS_MAX_COUNT
    try:
        v = int(stripped, 10)
    except ValueError:
        log.warning(
            "Invalid %s value: %r; using built-in default %s",
            _RUN_EVENTS_MAX_COUNT_ENV,
            raw,
            _DEFAULT_RUN_EVENTS_MAX_COUNT,
        )
        return _DEFAULT_RUN_EVENTS_MAX_COUNT
    if v <= 0:
        return None
    return v


def parse_default_run_events_max_total_bytes() -> int | None:
    """Parse ``REPLAYT_MCP_BRIDGE_RUN_EVENTS_MAX_TOTAL_BYTES`` for ``persistence_list_run_events``.

    Returns ``None`` when the aggregate-size cap is disabled (env **0** or negative). When unset, empty, or invalid,
    returns the built-in default **32 MiB**. When set to a positive integer, returns that limit.
    """

    log = logging.getLogger("replayt_mcp_bridge")
    raw = os.environ.get(_RUN_EVENTS_MAX_TOTAL_BYTES_ENV)
    if raw is None:
        return _DEFAULT_RUN_EVENTS_MAX_TOTAL_BYTES
    stripped = raw.strip()
    if not stripped:
        return _DEFAULT_RUN_EVENTS_MAX_TOTAL_BYTES
    try:
        v = int(stripped, 10)
    except ValueError:
        log.warning(
            "Invalid %s value: %r; using built-in default %s",
            _RUN_EVENTS_MAX_TOTAL_BYTES_ENV,
            raw,
            _DEFAULT_RUN_EVENTS_MAX_TOTAL_BYTES,
        )
        return _DEFAULT_RUN_EVENTS_MAX_TOTAL_BYTES
    if v <= 0:
        return None
    return v


_DEFAULT_RUN_EVENTS_REDACT_KEYS_RAW = "api_key,auth,bearer,cookie,credential,password,private_key,secret,token"
_RUN_EVENTS_REDACT_KEYS_ENV = "REPLAYT_MCP_BRIDGE_RUN_EVENTS_REDACT_KEYS"


def parse_run_events_redact_keys() -> tuple[str, ...]:
    """Return the normalized top-level key markers used when redacting run-event payloads.

    Defaults to ``api_key,auth,bearer,cookie,credential,password,private_key,secret,token`` when the env is unset or
    blank. Tokens are lowercased, ``-`` becomes ``_``, empty entries are dropped, and duplicates are removed while
    preserving order. If normalization removes every token from a non-empty env value, the built-in default applies.
    """

    raw = os.environ.get(_RUN_EVENTS_REDACT_KEYS_ENV)
    source = _DEFAULT_RUN_EVENTS_REDACT_KEYS_RAW if raw is None else raw
    seen: set[str] = set()
    tokens: list[str] = []
    for part in source.split(","):
        marker = part.strip().lower().replace("-", "_")
        if not marker or marker in seen:
            continue
        seen.add(marker)
        tokens.append(marker)
    if tokens:
        return tuple(tokens)
    if raw is not None:
        return tuple(
            part.strip()
            for part in _DEFAULT_RUN_EVENTS_REDACT_KEYS_RAW.split(",")
            if part.strip()
        )
    return ()


def _default_log_dir() -> Path:
    return Path.cwd() / ".logs"


def resolve_log_dir() -> Path:
    raw = os.environ.get("REPLAYT_LOG_DIR")
    return Path(raw).expanduser() if raw else _default_log_dir()


def _stderr_is_interactive() -> bool:
    try:
        return bool(sys.stderr.isatty())
    except Exception:  # pragma: no cover - defensive for exotic stderr replacements
        return False


def configure_logging() -> logging.Logger:
    log_dir = resolve_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("replayt_mcp_bridge")
    logger.setLevel(resolve_log_level_from_env())
    logger.propagate = False

    log_path = log_dir / "bridge.log"
    formatter = logging.Formatter("%(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logger.handlers.clear()
    logger.addHandler(file_handler)

    if _stderr_is_interactive():
        stderr_handler = logging.StreamHandler()
        stderr_handler.setFormatter(formatter)
        logger.addHandler(stderr_handler)

    return logger
