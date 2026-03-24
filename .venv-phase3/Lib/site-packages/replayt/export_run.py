"""Sanitize recorded JSONL events for redacted export bundles (share / compliance helpers)."""

from __future__ import annotations

import copy
import json
from typing import Any

from replayt.types import LogMode


def sanitize_event(event: dict[str, Any], mode: LogMode) -> dict[str, Any]:
    """Return a deep copy of one JSONL event with payloads trimmed to ``mode`` (for exports, not re-run)."""

    if mode == LogMode.full:
        return copy.deepcopy(event)
    out = copy.deepcopy(event)
    typ = out.get("type")
    payload = out.get("payload")
    if not isinstance(payload, dict):
        return out
    p = dict(payload)
    if typ == "run_started":
        p["inputs"] = {}
    elif typ == "context_snapshot":
        p["data"] = {"_redacted": True}
    elif typ == "llm_request":
        p.pop("messages", None)
        if mode == LogMode.structured_only:
            p.pop("messages_summary", None)
    elif typ == "llm_response":
        p.pop("content", None)
        if mode == LogMode.structured_only:
            p.pop("content_preview", None)
        elif mode == LogMode.redacted:
            prev = p.get("content_preview")
            if isinstance(prev, str) and len(prev) > 400:
                p["content_preview"] = prev[:400] + "…"
    elif typ == "tool_call":
        p["arguments"] = {"_redacted": True}
    elif typ == "tool_result":
        p["result"] = None
    elif typ == "run_failed":
        err = p.get("error")
        if isinstance(err, dict):
            e2 = dict(err)
            e2.pop("traceback", None)
            p["error"] = e2
    out["payload"] = p
    return out


def events_to_jsonl_lines(events: list[dict[str, Any]], mode: LogMode) -> list[bytes]:
    lines: list[bytes] = []
    for ev in events:
        sanitized = sanitize_event(ev, mode)
        lines.append(json.dumps(sanitized, ensure_ascii=False, default=str).encode("utf-8") + b"\n")
    return lines
