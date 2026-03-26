"""Normalize LLM-related settings from defaults, YAML, and JSON."""

from __future__ import annotations

import json
import math
from typing import Any

# OpenAI-compatible chat APIs accept up to four stop sequences; cap string length to keep logs bounded.
_MAX_LLM_STOP_SLOTS = 4
_MAX_LLM_STOP_STR_CHARS = 512

# Audit-only tags on ``effective`` (not sent in HTTP); keep lists small for JSONL and jq.
_MAX_LLM_TAG_COUNT = 16
_MAX_LLM_TAG_CHARS = 64


def coerce_llm_extra_body(
    value: Any,
    *,
    reserved_keys: set[str] | frozenset[str] | None = None,
) -> dict[str, Any] | None:
    """Normalize provider-specific JSON fields for ``/chat/completions``.

    ``None`` or ``{}`` means omit the extra body entirely. Keys must be non-empty strings,
    values must be JSON-serializable, and reserved core payload fields are rejected.
    """

    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(f"extra_body must be a dict[str, Any], got {type(value).__name__}")
    normalized: dict[str, Any] = {}
    reserved = set(reserved_keys or ())
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str):
            raise TypeError(f"extra_body keys must be strings, got {type(raw_key).__name__}")
        key = raw_key.strip()
        if not key:
            raise ValueError("extra_body keys must be non-empty strings")
        if key in reserved:
            joined = ", ".join(sorted(reserved))
            raise ValueError(f"extra_body key {key!r} conflicts with core chat fields; use one of: {joined}")
        normalized[key] = raw_value
    if not normalized:
        return None
    try:
        # Round-trip so tuples and similar JSON values normalize to the shape we actually send/log.
        return json.loads(json.dumps(normalized))
    except (TypeError, ValueError) as exc:
        raise TypeError(f"extra_body must be JSON-serializable: {exc}") from exc


def coerce_llm_stop_sequences(value: Any) -> list[str] | None:
    """Normalize ``stop`` for OpenAI-style ``/chat/completions`` (omit from JSON when ``None``)."""

    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return None if not s else [s]
    if isinstance(value, (list, tuple)):
        seqs: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise TypeError(f"stop sequences must be strings, got {type(item).__name__}")
            t = item.strip()
            if t:
                seqs.append(t)
        if not seqs:
            return None
    else:
        raise TypeError(f"stop must be str, list, or tuple, got {type(value).__name__}")
    if len(seqs) > _MAX_LLM_STOP_SLOTS:
        raise ValueError(f"at most {_MAX_LLM_STOP_SLOTS} stop sequences allowed, got {len(seqs)}")
    for i, s in enumerate(seqs):
        if len(s) > _MAX_LLM_STOP_STR_CHARS:
            raise ValueError(
                f"stop sequence [{i}] length {len(s)} exceeds max {_MAX_LLM_STOP_STR_CHARS} characters"
            )
    return seqs


def coerce_llm_tags(value: Any) -> tuple[str, ...] | None:
    """Normalize ``llm_tags`` for :class:`~replayt.llm.LLMBridge` defaults and per-call overrides.

    Tags are logged on ``effective`` (and mirrored on LLM JSONL lines) for analytics; they are **not**
    forwarded to ``/chat/completions`` unless you duplicate them in ``extra_body`` yourself.
    """

    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if len(s) > _MAX_LLM_TAG_CHARS:
            raise ValueError(f"llm_tags entry length {len(s)} exceeds max {_MAX_LLM_TAG_CHARS} characters")
        return (s,)
    if isinstance(value, (list, tuple)):
        acc: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise TypeError(f"llm_tags entries must be strings, got {type(item).__name__}")
            t = item.strip()
            if not t:
                continue
            if len(t) > _MAX_LLM_TAG_CHARS:
                raise ValueError(
                    f"llm_tags entry length {len(t)} exceeds max {_MAX_LLM_TAG_CHARS} characters"
                )
            acc.append(t)
        if not acc:
            return None
        unique_sorted = tuple(sorted(set(acc)))
        if len(unique_sorted) > _MAX_LLM_TAG_COUNT:
            raise ValueError(f"at most {_MAX_LLM_TAG_COUNT} llm_tags allowed, got {len(unique_sorted)}")
        return unique_sorted
    raise TypeError(f"llm_tags must be str, list, or tuple, got {type(value).__name__}")


def merge_llm_tag_tuples(
    base: tuple[str, ...] | None,
    extra: tuple[str, ...] | None,
) -> tuple[str, ...] | None:
    """Union two normalized tag tuples (sorted unique) and enforce the tag count cap."""

    merged = tuple(sorted(set(base or ()) | set(extra or ())))
    if not merged:
        return None
    if len(merged) > _MAX_LLM_TAG_COUNT:
        raise ValueError(f"at most {_MAX_LLM_TAG_COUNT} llm_tags allowed after merge, got {len(merged)}")
    return merged


def coerce_temperature(value: Any, *, default: float = 0.0) -> float:
    """Parse temperature; rejects bool (Python bool is a subclass of int).

    Values must be finite and within ``[0, 2]``, matching OpenAI-style chat ``temperature`` bounds.
    """

    if value is None:
        out = float(default)
    elif isinstance(value, bool):
        raise TypeError("temperature cannot be a boolean")
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            out = float(default)
        else:
            out = float(s)
    else:
        out = float(value)
    if not math.isfinite(out):
        raise ValueError("temperature must be a finite number")
    if out < 0.0 or out > 2.0:
        raise ValueError(f"temperature must be between 0 and 2 inclusive (OpenAI-style chat API), got {out}")
    return out


def coerce_timeout_seconds(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError("timeout_seconds cannot be a boolean")
    if isinstance(value, str):
        s = value.strip()
        if not s:
            raise ValueError("timeout_seconds cannot be empty")
        out = float(s)
    else:
        out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError("timeout_seconds must be a finite number greater than zero")
    return out


def coerce_top_p(value: Any) -> float | None:
    """Return ``top_p`` as a float in ``[0, 1]`` or ``None`` to omit it."""

    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("top_p cannot be a boolean")
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        out = float(s)
    else:
        out = float(value)
    if not math.isfinite(out):
        raise ValueError("top_p must be a finite number")
    if out < 0 or out > 1:
        raise ValueError(f"top_p must be between 0 and 1 inclusive, got {out}")
    return out


def coerce_openai_penalty(value: Any) -> float | None:
    """``frequency_penalty`` / ``presence_penalty`` for OpenAI-compatible APIs (range ``[-2, 2]``).

    ``None`` means omit the field from the HTTP payload (provider default).
    """

    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("penalty cannot be a boolean")
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        out = float(s)
    else:
        out = float(value)
    if not math.isfinite(out):
        raise ValueError("penalty must be a finite number")
    if out < -2.0 or out > 2.0:
        raise ValueError(f"penalty must be between -2 and 2 inclusive, got {out}")
    return out


def coerce_llm_seed(value: Any) -> int | None:
    """Optional integer ``seed`` for providers that support deterministic sampling."""

    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("seed cannot be a boolean")
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        return int(s, 10)
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"seed must be a whole number, got {value}")
        return int(value)
    return int(value)


def coerce_max_tokens_for_api(value: Any) -> int | None:
    """Return a non-negative int for the HTTP client, or None to omit max_tokens.

    Accepts int, floats (rounded), or numeric strings (e.g. from JSON merges).
    """

    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("max_tokens cannot be a boolean")
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("max_tokens must be a finite number")
        return max(0, int(round(value)))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            x = float(s)
        except ValueError as exc:
            raise ValueError(f"max_tokens must be numeric, got {s!r}") from exc
        if not math.isfinite(x):
            raise ValueError("max_tokens must be a finite number")
        return max(0, int(round(x)))
    raise TypeError(f"max_tokens must be numeric or numeric string, got {type(value).__name__}")


# Cap additional POST attempts so a typo cannot stall a run unbounded.
_MAX_HTTP_RETRIES = 25


def coerce_http_retries(value: Any) -> int:
    """Normalize ``http_retries`` (extra POST attempts after the first; same as ``LLMSettings.http_retries``)."""

    if isinstance(value, bool):
        raise TypeError("http_retries cannot be a boolean")
    if isinstance(value, str):
        s = value.strip()
        if not s:
            raise ValueError("http_retries cannot be empty")
        n = int(s, 10)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("http_retries must be a finite number")
        if not value.is_integer():
            raise ValueError(f"http_retries must be a whole number, got {value}")
        n = int(value)
    elif isinstance(value, int):
        n = value
    else:
        raise TypeError(f"http_retries must be int-like, got {type(value).__name__}")
    if n < 0:
        raise ValueError("http_retries must be >= 0")
    if n > _MAX_HTTP_RETRIES:
        raise ValueError(f"http_retries must be <= {_MAX_HTTP_RETRIES}, got {n}")
    return n


def coerce_llm_response_format(value: Any, *, max_json_chars: int = 250_000) -> dict[str, Any] | None:
    """Normalize OpenAI-style ``response_format`` for ``/chat/completions``.

    ``None`` or ``{}`` after normalization means omit the field. Values must be JSON-serializable.
    Serialized size is capped (same order of magnitude as embedded parse schemas) so logs stay bounded.
    """

    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(f"response_format must be a dict[str, Any], got {type(value).__name__}")
    try:
        normalized: dict[str, Any] = json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError) as exc:
        raise TypeError(f"response_format must be JSON-serializable: {exc}") from exc
    if not normalized:
        return None
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    if len(canonical) > max_json_chars:
        raise ValueError(
            f"response_format JSON serializes to {len(canonical)} characters, above max_json_chars ({max_json_chars})"
        )
    return normalized
