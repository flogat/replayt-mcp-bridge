from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from replayt.llm_coercion import (
    coerce_http_retries,
    coerce_llm_extra_body,
    coerce_llm_seed,
    coerce_llm_stop_sequences,
    coerce_llm_tags,
    coerce_max_tokens_for_api,
    coerce_openai_penalty,
    coerce_temperature,
    coerce_timeout_seconds,
    coerce_top_p,
    merge_llm_tag_tuples,
)
from replayt.security import sanitize_base_url_for_output
from replayt.types import LogMode

T = TypeVar("T", bound=BaseModel)


class _HTTPStreamClient(Protocol):
    def stream(self, method: str, url: str, **kwargs: Any) -> Any: ...

    def close(self) -> None: ...


# Cap `{` probes so pathological multi-megabyte text cannot burn CPU in raw_decode attempts.
_MAX_JSON_OBJECT_BRACE_STARTS = 50_000

# Cap Pydantic issues on ``structured_output_failed`` so one pathological model payload cannot bloat JSONL.
_MAX_STRUCTURED_VALIDATION_ISSUES = 32

# Short per-call tag for JSONL when one step issues multiple LLM round trips (distinct from run-level ``experiment``).
_MAX_CALL_LABEL_CHARS = 128

# ``complete_text(..., response_format=...)`` uses this sentinel so ``None`` can mean "omit from HTTP".
_RF_UNSET = object()


def _extract_json_object(text: str, *, max_brace_starts: int = _MAX_JSON_OBJECT_BRACE_STARTS) -> str:
    """Parse JSON object spans from *text* and pick a single ``{...}`` result.

    Nested objects produce multiple valid spans (inner and outer). Spans **strictly contained**
    in another dict span are dropped. If more than one span remains (e.g. two sibling objects),
    the **last** span wins so a trailing final JSON object beats an earlier draft.
    """

    text = text.strip()
    decoder = json.JSONDecoder()
    spans: list[tuple[int, int, str]] = []
    brace_starts = 0
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        brace_starts += 1
        if brace_starts > max_brace_starts:
            raise ValueError(
                f"Too many '{{' characters to scan for a JSON object (limit {max_brace_starts}); "
                "response may be malformed or not JSON-object-shaped."
            )
        try:
            obj, end = decoder.raw_decode(text[idx:])
        except ValueError:
            continue
        if isinstance(obj, dict):
            end_idx = idx + end
            spans.append((idx, end_idx, text[idx:end_idx]))

    if not spans:
        raise ValueError(
            "No JSON object found in model response (expected a {...} object). "
            "If the model returned markdown fences, prose only, or non-object JSON, adjust the prompt "
            "or parse the text manually."
        )

    def strictly_inside(inner: tuple[int, int, str], outer: tuple[int, int, str]) -> bool:
        a0, a1, _ = inner
        b0, b1, _ = outer
        return b0 < a0 and a1 < b1

    maximal: list[tuple[int, int, str]] = []
    for sp in spans:
        if any(strictly_inside(sp, other) for other in spans):
            continue
        maximal.append(sp)
    if not maximal:
        maximal = list(spans)
    return maximal[-1][2]


def _stable_json_sha256(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _top_level_llm_tags(effective: dict[str, Any]) -> list[str] | None:
    raw = effective.get("llm_tags")
    if isinstance(raw, list) and raw:
        return list(raw)
    return None


def _coerce_call_label(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return s[:_MAX_CALL_LABEL_CHARS]


def _coerce_bridge_response_format(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TypeError("response_format must be a dict")
    try:
        json.dumps(raw, sort_keys=True, default=str)
    except TypeError as exc:
        raise TypeError(f"response_format must be JSON-serializable: {exc}") from exc
    return dict(raw)


def _response_format_for_effective(rf: dict[str, Any]) -> dict[str, Any] | None:
    """Compact OpenAI-style ``response_format`` for ``effective`` (no full ``json_schema.schema`` tree)."""

    out: dict[str, Any] = {}
    t = rf.get("type")
    if isinstance(t, str) and t.strip():
        out["type"] = t.strip()
    js = rf.get("json_schema")
    if isinstance(js, dict):
        name = js.get("name")
        if isinstance(name, str) and name.strip():
            out["json_schema_name"] = name.strip()
        if "strict" in js:
            out["json_schema_strict"] = bool(js["strict"])
    return out or None


def _pydantic_validation_issues_for_log(exc: BaseException) -> tuple[list[dict[str, Any]], int] | None:
    """Return a bounded list of Pydantic v2 validation errors plus the full error count, or None."""

    if not isinstance(exc, ValidationError):
        return None
    raw = exc.errors()
    total = len(raw)
    if total == 0:
        return None
    clipped = raw[:_MAX_STRUCTURED_VALIDATION_ISSUES]
    issues: list[dict[str, Any]] = []
    for err in clipped:
        loc = err.get("loc")
        loc_out: list[Any] = []
        if isinstance(loc, tuple):
            for part in loc:
                if isinstance(part, (str, int)):
                    loc_out.append(part)
                else:
                    loc_out.append(str(part))
        et = err.get("type")
        issues.append(
            {
                "type": str(et) if et is not None else None,
                "loc": loc_out,
                "msg": str(err.get("msg", "")),
            }
        )
    return issues, total


def _request_fingerprints(
    *,
    messages: list[dict[str, Any]],
    effective: dict[str, Any],
    schema_json: dict[str, Any] | None = None,
) -> dict[str, str]:
    out = {
        "messages_sha256": _stable_json_sha256(messages),
        "effective_sha256": _stable_json_sha256(effective),
    }
    if schema_json is not None:
        out["schema_sha256"] = _stable_json_sha256(schema_json)
    return out


@dataclass
class LLMSettings:
    api_key: str | None = None
    provider: str | None = None
    base_url: str = "http://127.0.0.1:11434/v1"
    model: str = "llama3.2"
    timeout_seconds: float = 120.0
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    seed: int | None = None
    max_tokens: int | None = None
    #: Up to four stop strings forwarded to OpenAI-compatible ``/chat/completions`` when set.
    stop: tuple[str, ...] | None = None
    #: Extra JSON body fields for OpenAI-compatible gateways (for example provider-specific knobs).
    extra_body: dict[str, Any] = field(default_factory=dict)
    extra_headers: dict[str, str] = field(default_factory=dict)
    http_retries: int = 0
    #: Upper bound on ``LLMBridge.parse`` response text length (after ``complete_text``) before ``json.loads``.
    max_parse_response_chars: int = 4_000_000
    #: Hard cap on HTTP response body size for ``/chat/completions`` (bytes), read via streaming.
    max_response_bytes: int = 32 * 1024 * 1024
    #: Upper bound on JSON Schema text embedded in :meth:`LLMBridge.parse` system prompts.
    max_schema_json_chars: int = 250_000
    #: Default model slug when routing Anthropic traffic through an OpenAI-compatible gateway.
    anthropic_gateway_model: ClassVar[str] = "claude-3-5-sonnet-20241022"

    _provider_presets: ClassVar[dict[str, tuple[str, str]]] = {
        "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
        "ollama": ("http://127.0.0.1:11434/v1", "llama3.2"),
        "groq": ("https://api.groq.com/openai/v1", "llama-3.1-8b-instant"),
        "together": ("https://api.together.xyz/v1", "meta-llama/Llama-3.1-8B-Instruct-Turbo"),
        "openrouter": ("https://openrouter.ai/api/v1", "anthropic/claude-sonnet-4.6"),
    }

    @classmethod
    def _anthropic_gateway_error(cls) -> str:
        return (
            "Provider 'anthropic' requires OPENAI_BASE_URL to point at an OpenAI-compatible gateway; "
            "Anthropic's native API does not expose /chat/completions. Set OPENAI_BASE_URL explicitly "
            "or call the anthropic SDK inside a workflow step."
        )

    @classmethod
    def for_provider(cls, name: str, *, api_key: str | None = None, model: str | None = None) -> LLMSettings:
        """Build settings from a named OpenAI-*compatible* preset (URLs only; some vendors need a compat proxy).

        Presets: ``openai``, ``ollama``, ``groq``, ``together``, ``openrouter``. Anthropic's native
        API is not OpenAI-compatible; use ``OPENAI_BASE_URL`` with an OpenAI-compatible gateway or call
        Anthropic's SDK inside a workflow step.
        """

        key = name.strip().lower()
        if key == "anthropic":
            raise ValueError(cls._anthropic_gateway_error())
        if key not in cls._provider_presets:
            allowed = ", ".join(sorted(cls._provider_presets.keys()))
            raise ValueError(f"Unknown provider {name!r}; expected one of: {allowed}")
        base_url, default_model = cls._provider_presets[key]
        return cls(
            api_key=api_key,
            provider=key,
            base_url=base_url,
            model=model or default_model,
        )

    @classmethod
    def _limits_from_env(cls) -> tuple[int, int]:
        max_rb = 32 * 1024 * 1024
        raw_rb = os.environ.get("REPLAYT_LLM_MAX_RESPONSE_BYTES", "").strip()
        if raw_rb:
            try:
                max_rb = max(1024, int(raw_rb))
            except ValueError:
                raise ValueError(
                    f"REPLAYT_LLM_MAX_RESPONSE_BYTES must be an integer number of bytes, got {raw_rb!r}"
                ) from None
        max_schema = 250_000
        raw_schema = os.environ.get("REPLAYT_LLM_MAX_SCHEMA_CHARS", "").strip()
        if raw_schema:
            try:
                max_schema = max(1024, int(raw_schema))
            except ValueError:
                raise ValueError(
                    f"REPLAYT_LLM_MAX_SCHEMA_CHARS must be a positive integer, got {raw_schema!r}"
                ) from None
        return max_rb, max_schema

    @classmethod
    def from_sources(
        cls,
        *,
        provider: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> LLMSettings:
        provider_name = (provider or "").strip().lower()
        resolved_base_url = (base_url or "").strip()
        resolved_model = (model or "").strip()
        if provider_name:
            if provider_name == "anthropic":
                if not resolved_base_url:
                    raise ValueError(cls._anthropic_gateway_error())
                preset_base = resolved_base_url
                preset_model = cls.anthropic_gateway_model
            else:
                preset = cls.for_provider(provider_name)
                preset_base = preset.base_url
                preset_model = preset.model
        else:
            preset_base, preset_model = cls._provider_presets["ollama"]
        max_rb, max_schema = cls._limits_from_env()
        return cls(
            api_key=api_key,
            provider=provider_name or None,
            base_url=resolved_base_url or preset_base,
            model=resolved_model or preset_model,
            max_response_bytes=max_rb,
            max_schema_json_chars=max_schema,
        )

    @classmethod
    def from_env(cls) -> LLMSettings:
        return cls.from_sources(
            provider=os.environ.get("REPLAYT_PROVIDER"),
            base_url=os.environ.get("OPENAI_BASE_URL"),
            model=os.environ.get("REPLAYT_MODEL"),
            api_key=os.environ.get("OPENAI_API_KEY"),
        )


# 500 included: many gateways return it for transient upstream failures (retry-safe in practice).
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 30.0

# Bounded gateway response metadata for JSONL correlation (vendor dashboards, edge traces).
_MAX_HTTP_CORRELATION_ID_CHARS = 128
_MAX_HTTP_RESPONSE_PROCESSING_MS = 3_600_000

_CORRELATION_TRANSPORT_KEYS: tuple[str, ...] = (
    "http_response_request_id",
    "http_response_processing_ms",
    "http_response_cf_ray",
)


def _header_get_ci(headers: Any, name: str) -> str | None:
    """Return a stripped header value, case-insensitive for plain dict-like mappings."""

    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if callable(getter):
        v = getter(name)
        if v is not None:
            s = str(v).strip()
            return s or None
    try:
        want = name.lower()
        for k, val in headers.items():
            if str(k).lower() == want:
                s = str(val).strip()
                return s or None
    except (AttributeError, TypeError):
        pass
    return None


def _http_correlation_breadcrumbs(headers: Any) -> dict[str, Any]:
    """Pick small, stable fields from successful chat-completions HTTP response headers."""

    out: dict[str, Any] = {}
    rid = _header_get_ci(headers, "x-request-id") or _header_get_ci(headers, "x-correlation-id")
    if rid is not None and len(rid) <= _MAX_HTTP_CORRELATION_ID_CHARS:
        out["http_response_request_id"] = rid
    proc_raw = _header_get_ci(headers, "openai-processing-ms")
    if proc_raw is not None:
        try:
            ms = int(proc_raw)
            if 0 <= ms <= _MAX_HTTP_RESPONSE_PROCESSING_MS:
                out["http_response_processing_ms"] = ms
        except ValueError:
            pass
    cf = _header_get_ci(headers, "cf-ray")
    if cf is not None and len(cf) <= _MAX_HTTP_CORRELATION_ID_CHARS:
        out["http_response_cf_ray"] = cf
    return out


def _retry_after_delay_seconds(raw: str | None) -> float:
    """Parse ``Retry-After`` as a non-negative delay in seconds (numeric form only).

    HTTP-date values are ignored (``float`` parse fails). Non-finite or negative
    values fall back to :data:`_RETRY_BASE_DELAY` so :func:`time.sleep` never
    sees invalid durations.
    """

    if raw is None:
        return _RETRY_BASE_DELAY
    s = str(raw).strip()
    if not s:
        return _RETRY_BASE_DELAY
    try:
        delay = float(s)
    except (ValueError, TypeError):
        return _RETRY_BASE_DELAY
    if not math.isfinite(delay) or delay < 0:
        return _RETRY_BASE_DELAY
    return delay


_CHAT_COMPLETIONS_RESERVED_FIELDS = frozenset(
    {
        "model",
        "messages",
        "temperature",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
        "seed",
        "max_tokens",
        "stop",
        "response_format",
        "llm_tags",
    }
)


def _drain_stream_with_limit(response: httpx.Response, byte_limit: int) -> None:
    n = 0
    for chunk in response.iter_bytes():
        n += len(chunk)
        if n >= byte_limit:
            break


def _read_response_body_capped(response: httpx.Response, max_bytes: int) -> bytes:
    buf = bytearray()
    for chunk in response.iter_bytes():
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise RuntimeError(
                f"Chat completions response body exceeds max_response_bytes ({max_bytes}); "
                "raise LLMSettings.max_response_bytes if needed."
            )
    return bytes(buf)


def _raise_chat_completions_401_hint(settings: LLMSettings) -> None:
    """Turn bare HTTP 401 into an onboarding-friendly error (missing vs wrong key)."""

    if not (settings.api_key or "").strip():
        raise RuntimeError(
            "LLM HTTP 401 Unauthorized while OPENAI_API_KEY is unset. "
            "Export OPENAI_API_KEY for live calls (see `.env.example` from `replayt init` and docs/QUICKSTART.md), "
            "run `replayt doctor`, or use offline placeholder responses: `replayt run --dry-run` or "
            "`replayt try` without `--live`."
        )
    raise RuntimeError(
        "LLM HTTP 401 Unauthorized. Check OPENAI_API_KEY for this OPENAI_BASE_URL / provider "
        "(run `replayt doctor` for connectivity when you trust the host)."
    )


class OpenAICompatClient:
    """Minimal chat.completions client for OpenAI-compatible servers."""

    def __init__(
        self,
        settings: LLMSettings | None = None,
        *,
        http_client: _HTTPStreamClient | None = None,
        http_client_factory: Callable[[float], _HTTPStreamClient] | None = None,
    ) -> None:
        self.settings = settings or LLMSettings.from_env()
        self._http: _HTTPStreamClient | None = http_client
        self._http_client_factory = http_client_factory or (lambda timeout: httpx.Client(timeout=timeout))

    @property
    def _client(self) -> _HTTPStreamClient:
        if self._http is None:
            self._http = self._http_client_factory(self.settings.timeout_seconds)
        return self._http

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    def chat_completions(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.0,
        top_p: float | None = None,
        frequency_penalty: float | None = None,
        presence_penalty: float | None = None,
        seed: int | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        stop: list[str] | None = None,
        http_retries: int | None = None,
        transport_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = (base_url or self.settings.base_url).rstrip("/") + "/chat/completions"
        eff_max = max_tokens if max_tokens is not None else self.settings.max_tokens
        payload: dict[str, Any] = {
            "model": model or self.settings.model,
            "messages": messages,
            "temperature": temperature,
        }
        if top_p is not None:
            payload["top_p"] = top_p
        if frequency_penalty is not None:
            payload["frequency_penalty"] = frequency_penalty
        if presence_penalty is not None:
            payload["presence_penalty"] = presence_penalty
        if seed is not None:
            payload["seed"] = seed
        if eff_max is not None:
            payload["max_tokens"] = eff_max
        if stop:
            payload["stop"] = stop
        if response_format is not None:
            payload["response_format"] = response_format
        default_extra_body = coerce_llm_extra_body(
            self.settings.extra_body,
            reserved_keys=_CHAT_COMPLETIONS_RESERVED_FIELDS,
        )
        if extra_body is not None:
            call_extra_body = coerce_llm_extra_body(
                extra_body,
                reserved_keys=_CHAT_COMPLETIONS_RESERVED_FIELDS,
            )
            merged_extra_body = None if call_extra_body is None else {**(default_extra_body or {}), **call_extra_body}
        else:
            merged_extra_body = default_extra_body
        if merged_extra_body:
            payload.update(merged_extra_body)
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            **(self.settings.extra_headers or {}),
            **(extra_headers or {}),
        }
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        timeout = timeout_seconds if timeout_seconds is not None else self.settings.timeout_seconds
        retry_budget = self.settings.http_retries if http_retries is None else http_retries
        max_attempts = max(retry_budget + 1, 1)
        cap = self.settings.max_response_bytes
        drain_cap = min(cap, 65_536)

        for attempt in range(max_attempts):
            try:
                with self._client.stream("POST", url, json=payload, headers=headers, timeout=timeout) as r:
                    status_code = int(r.status_code)
                    if status_code in _RETRYABLE_STATUS_CODES and attempt < max_attempts - 1:
                        _drain_stream_with_limit(r, drain_cap)
                        retry_after = r.headers.get("retry-after")
                        delay = min(
                            _retry_after_delay_seconds(retry_after) * (2**attempt),
                            _RETRY_MAX_DELAY,
                        )
                        time.sleep(delay)
                        continue
                    if status_code == 401:
                        _raise_chat_completions_401_hint(self.settings)
                    r.raise_for_status()
                    cl = r.headers.get("content-length")
                    if cl is not None:
                        try:
                            if int(cl) > cap:
                                raise RuntimeError(
                                    f"Chat completions Content-Length ({cl}) exceeds max_response_bytes ({cap})"
                                )
                        except ValueError:
                            pass
                    raw = _read_response_body_capped(r, cap)
                    # Snapshot headers before exiting the stream context (response may be closed after ``with``).
                    http_correlation = _http_correlation_breadcrumbs(r.headers)
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise RuntimeError(
                        f"Chat completions response was not valid UTF-8: {exc}; body_bytes={len(raw)}"
                    ) from exc
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"Chat completions response was not valid JSON: {exc}; body_bytes={len(raw)}"
                    ) from exc
                if transport_meta is not None:
                    transport_meta.clear()
                    transport_meta["http_attempts"] = attempt + 1
                    transport_meta["http_status"] = status_code
                    transport_meta.update(http_correlation)
                return parsed
            except httpx.TransportError:
                if attempt < max_attempts - 1:
                    time.sleep(min(_RETRY_BASE_DELAY * (2**attempt), _RETRY_MAX_DELAY))
                    continue
                raise
        raise RuntimeError(
            "replayt internal error: OpenAICompatClient.chat_completions exited without returning"
        )


class LLMBridge:
    """Per-run LLM helper that emits log events via callback."""

    def __init__(
        self,
        *,
        emit: Callable[[str, dict[str, Any]], None],
        client: OpenAICompatClient,
        log_mode: LogMode,
        state_getter: Callable[[], str | None],
        defaults: dict[str, Any] | None = None,
    ) -> None:
        self._emit = emit
        self._client = client
        self._log_mode = log_mode
        self._state_getter = state_getter
        self._defaults = defaults or {}

    def with_settings(
        self,
        *,
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        frequency_penalty: float | None = None,
        presence_penalty: float | None = None,
        seed: int | None = None,
        timeout_seconds: float | None = None,
        max_tokens: int | None = None,
        provider: str | None = None,
        base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict[str, Any] | None = None,
        native_response_format: bool | None = None,
        experiment: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        stop: list[str] | tuple[str, ...] | str | None = None,
        call_label: str | None = None,
        http_retries: int | None = None,
        llm_tags: list[str] | tuple[str, ...] | str | None = None,
    ) -> LLMBridge:
        """Return a new bridge with merged per-call defaults (logged on each request as ``effective``)."""

        merged: dict[str, Any] = {**self._defaults}
        if model is not None:
            merged["model"] = model
        if temperature is not None:
            merged["temperature"] = temperature
        if top_p is not None:
            merged["top_p"] = top_p
        if frequency_penalty is not None:
            merged["frequency_penalty"] = frequency_penalty
        if presence_penalty is not None:
            merged["presence_penalty"] = presence_penalty
        if seed is not None:
            merged["seed"] = seed
        if timeout_seconds is not None:
            merged["timeout_seconds"] = timeout_seconds
        if max_tokens is not None:
            merged["max_tokens"] = max_tokens
        if provider is not None:
            merged["provider"] = provider
        if base_url is not None:
            merged["base_url"] = base_url
        if extra_headers:
            h = dict(merged.get("extra_headers") or {})
            h.update(extra_headers)
            merged["extra_headers"] = h
        if extra_body is not None:
            coerced_extra_body = coerce_llm_extra_body(
                extra_body,
                reserved_keys=_CHAT_COMPLETIONS_RESERVED_FIELDS,
            )
            if coerced_extra_body is None:
                merged.pop("extra_body", None)
            else:
                body = dict(merged.get("extra_body") or {})
                body.update(coerced_extra_body)
                merged["extra_body"] = body
        if native_response_format is not None:
            merged["native_response_format"] = bool(native_response_format)
        if experiment is not None:
            prev = merged.get("experiment")
            if isinstance(prev, dict):
                merged["experiment"] = {**prev, **experiment}
            else:
                merged["experiment"] = dict(experiment)
        if stop is not None:
            coerced_stop = coerce_llm_stop_sequences(stop)
            if coerced_stop is None:
                merged.pop("stop", None)
            else:
                merged["stop"] = coerced_stop
        if call_label is not None:
            coerced_label = _coerce_call_label(call_label)
            if coerced_label:
                merged["call_label"] = coerced_label
            else:
                merged.pop("call_label", None)
        if http_retries is not None:
            merged["http_retries"] = coerce_http_retries(http_retries)
        if llm_tags is not None:
            coerced_tags = coerce_llm_tags(llm_tags)
            if coerced_tags is None:
                merged.pop("llm_tags", None)
            else:
                prev_tags = coerce_llm_tags(merged.get("llm_tags"))
                merged["llm_tags"] = merge_llm_tag_tuples(prev_tags, coerced_tags)
        if response_format is not None:
            if response_format == {}:
                merged.pop("response_format", None)
            else:
                merged["response_format"] = _coerce_bridge_response_format(response_format)
        return LLMBridge(
            emit=self._emit,
            client=self._client,
            log_mode=self._log_mode,
            state_getter=self._state_getter,
            defaults=merged,
        )

    def _merge_call(
        self,
        *,
        model: str | None,
        temperature: float,
        top_p: float | None,
        frequency_penalty: float | None,
        presence_penalty: float | None,
        seed: int | None,
        max_tokens: int | None,
        timeout_seconds: float | None,
        provider: str | None,
        base_url: str | None,
        extra_headers: dict[str, str] | None,
        extra_body: dict[str, Any] | None,
        stop: list[str] | tuple[str, ...] | str | None,
        http_retries: int | None = None,
        llm_tags: list[str] | tuple[str, ...] | str | None = None,
    ) -> tuple[dict[str, Any], dict[str, str], str, dict[str, Any] | None]:
        d = self._defaults
        base = self._client.settings
        eff_provider_raw = provider if provider is not None else d.get("provider", base.provider)
        eff_provider = str(eff_provider_raw).strip().lower() if eff_provider_raw not in (None, "") else None
        eff_base_url = str(base_url).strip() if base_url not in (None, "") else ""
        if not eff_base_url:
            default_base_url = d.get("base_url")
            eff_base_url = str(default_base_url).strip() if default_base_url not in (None, "") else ""
        if not eff_base_url:
            eff_base_url = base.base_url
        provider_default_model: str | None = None
        if eff_provider is not None:
            provider_settings = LLMSettings.from_sources(
                provider=eff_provider,
                base_url=eff_base_url or None,
            )
            eff_base_url = provider_settings.base_url
            provider_default_model = provider_settings.model
        eff_model = model if model is not None else d.get("model")
        if eff_model is None:
            eff_model = provider_default_model or base.model
        if "temperature" in d:
            eff_temp = coerce_temperature(d["temperature"], default=temperature)
        else:
            eff_temp = coerce_temperature(temperature, default=0.0)
        if top_p is not None:
            eff_top_p = coerce_top_p(top_p)
        elif "top_p" in d:
            eff_top_p = coerce_top_p(d.get("top_p"))
        else:
            eff_top_p = coerce_top_p(base.top_p)
        if frequency_penalty is not None:
            eff_freq_pen = coerce_openai_penalty(frequency_penalty)
        elif "frequency_penalty" in d:
            eff_freq_pen = coerce_openai_penalty(d.get("frequency_penalty"))
        else:
            eff_freq_pen = coerce_openai_penalty(base.frequency_penalty)
        if presence_penalty is not None:
            eff_pres_pen = coerce_openai_penalty(presence_penalty)
        elif "presence_penalty" in d:
            eff_pres_pen = coerce_openai_penalty(d.get("presence_penalty"))
        else:
            eff_pres_pen = coerce_openai_penalty(base.presence_penalty)
        if seed is not None:
            eff_seed = coerce_llm_seed(seed)
        elif "seed" in d:
            eff_seed = coerce_llm_seed(d.get("seed"))
        else:
            eff_seed = coerce_llm_seed(base.seed)
        eff_max = max_tokens if max_tokens is not None else d.get("max_tokens")
        if eff_max is None:
            eff_max = base.max_tokens
        eff_max = coerce_max_tokens_for_api(eff_max)
        eff_timeout = timeout_seconds if timeout_seconds is not None else d.get("timeout_seconds")
        if eff_timeout is None:
            eff_timeout = base.timeout_seconds
        eff_timeout = coerce_timeout_seconds(eff_timeout)
        if http_retries is not None:
            eff_http_retries = coerce_http_retries(http_retries)
        elif "http_retries" in d:
            eff_http_retries = coerce_http_retries(d["http_retries"])
        else:
            eff_http_retries = coerce_http_retries(base.http_retries)
        hdrs: dict[str, str] = {}
        hdrs.update(dict(base.extra_headers or {}))
        hdrs.update(dict(d.get("extra_headers") or {}))
        hdrs.update(extra_headers or {})
        base_extra_body = coerce_llm_extra_body(
            base.extra_body,
            reserved_keys=_CHAT_COMPLETIONS_RESERVED_FIELDS,
        )
        default_extra_body = coerce_llm_extra_body(
            d.get("extra_body"),
            reserved_keys=_CHAT_COMPLETIONS_RESERVED_FIELDS,
        )
        if extra_body is not None:
            call_extra_body = coerce_llm_extra_body(
                extra_body,
                reserved_keys=_CHAT_COMPLETIONS_RESERVED_FIELDS,
            )
            eff_extra_body = (
                None
                if call_extra_body is None
                else {**(base_extra_body or {}), **(default_extra_body or {}), **call_extra_body}
            )
        else:
            eff_extra_body = {**(base_extra_body or {}), **(default_extra_body or {})} or None
        if stop is not None:
            eff_stop = coerce_llm_stop_sequences(stop)
        elif "stop" in d:
            eff_stop = coerce_llm_stop_sequences(d.get("stop"))
        else:
            eff_stop = coerce_llm_stop_sequences(base.stop)
        effective: dict[str, Any] = {
            "model": eff_model,
            "base_url": sanitize_base_url_for_output(eff_base_url),
            "temperature": eff_temp,
            "top_p": eff_top_p,
            "frequency_penalty": eff_freq_pen,
            "presence_penalty": eff_pres_pen,
            "seed": eff_seed,
            "max_tokens": eff_max,
            "timeout_seconds": eff_timeout,
            "http_retries": eff_http_retries,
            "extra_header_names": sorted(hdrs.keys()),
        }
        if eff_provider is not None:
            effective["provider"] = eff_provider
        exp = d.get("experiment")
        if isinstance(exp, dict) and exp:
            effective["experiment"] = dict(exp)
        call_lab = _coerce_call_label(d.get("call_label"))
        if call_lab:
            effective["call_label"] = call_lab
        if eff_stop:
            effective["stop"] = list(eff_stop)
        if eff_extra_body:
            effective["extra_body"] = eff_extra_body
        d_tags = coerce_llm_tags(d.get("llm_tags"))
        call_tags = coerce_llm_tags(llm_tags) if llm_tags is not None else None
        eff_tag_tuple = merge_llm_tag_tuples(d_tags, call_tags)
        if eff_tag_tuple:
            effective["llm_tags"] = list(eff_tag_tuple)
        return effective, hdrs, eff_base_url, eff_extra_body

    @staticmethod
    def _serialize_error(exc: Exception) -> dict[str, str]:
        return {
            "type": exc.__class__.__name__,
            "module": exc.__class__.__module__,
            "message": str(exc),
        }

    def _request_text(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.0,
        top_p: float | None = None,
        frequency_penalty: float | None = None,
        presence_penalty: float | None = None,
        seed: int | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        provider: str | None = None,
        base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        effective_extras: dict[str, Any] | None = None,
        schema_json: dict[str, Any] | None = None,
        schema_name: str | None = None,
        stop: list[str] | tuple[str, ...] | str | None = None,
        http_retries: int | None = None,
        llm_tags: list[str] | tuple[str, ...] | str | None = None,
    ) -> tuple[str, dict[str, Any], dict[str, str], dict[str, Any]]:
        state = self._state_getter()
        effective, hdrs, eff_base_url, eff_extra_body = self._merge_call(
            model=model,
            temperature=temperature,
            top_p=top_p,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
            seed=seed,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            provider=provider,
            base_url=base_url,
            extra_headers=extra_headers,
            extra_body=extra_body,
            stop=stop,
            http_retries=http_retries,
            llm_tags=llm_tags,
        )
        if effective_extras:
            effective = {**effective, **effective_extras}
        if response_format is not None:
            rf_log = _response_format_for_effective(response_format)
            if rf_log:
                effective = {**effective, "response_format": rf_log}
        fingerprints = _request_fingerprints(messages=messages, effective=effective, schema_json=schema_json)
        eff_model = str(effective["model"])
        eff_temp = float(effective["temperature"])
        eff_top_p = coerce_top_p(effective.get("top_p"))
        eff_freq_pen = coerce_openai_penalty(effective.get("frequency_penalty"))
        eff_pres_pen = coerce_openai_penalty(effective.get("presence_penalty"))
        eff_seed = coerce_llm_seed(effective.get("seed"))
        eff_max = effective["max_tokens"]
        eff_timeout = float(effective["timeout_seconds"])
        eff_stop_list = list(effective["stop"]) if effective.get("stop") else None
        eff_http_retries = int(effective["http_retries"])

        req_payload: dict[str, Any] = {"state": state, "effective": effective}
        req_payload.update(fingerprints)
        if schema_name is not None:
            req_payload["schema_name"] = schema_name
        cl = effective.get("call_label")
        if isinstance(cl, str) and cl:
            req_payload["call_label"] = cl
        tl_tags = _top_level_llm_tags(effective)
        if tl_tags is not None:
            req_payload["llm_tags"] = tl_tags
        if self._log_mode == LogMode.full:
            req_payload["messages"] = messages
        elif self._log_mode == LogMode.redacted:
            req_payload["messages_summary"] = {
                "count": len(messages),
                "roles": [msg.get("role") for msg in messages],
            }
        self._emit("llm_request", req_payload)

        t0 = time.perf_counter()
        max_tok = coerce_max_tokens_for_api(eff_max)
        transport: dict[str, Any] = {}
        data = self._client.chat_completions(
            messages=messages,
            model=eff_model,
            temperature=eff_temp,
            top_p=eff_top_p,
            frequency_penalty=eff_freq_pen,
            presence_penalty=eff_pres_pen,
            seed=eff_seed,
            max_tokens=max_tok,
            timeout_seconds=eff_timeout,
            base_url=eff_base_url,
            extra_headers=hdrs if hdrs else None,
            extra_body=eff_extra_body,
            response_format=response_format,
            stop=eff_stop_list,
            http_retries=eff_http_retries,
            transport_meta=transport,
        )
        dt_ms = int((time.perf_counter() - t0) * 1000)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        usage = data.get("usage")
        finish_reason = choice.get("finish_reason")
        resp_payload: dict[str, Any] = {
            "state": state,
            "model": eff_model,
            "latency_ms": dt_ms,
            "usage": usage,
            "effective": effective,
            "finish_reason": finish_reason,
        }
        resp_payload.update(fingerprints)
        cid = data.get("id")
        if isinstance(cid, str) and cid.strip():
            resp_payload["chat_completion_id"] = cid.strip()
        fp = data.get("system_fingerprint")
        if isinstance(fp, str) and fp.strip():
            resp_payload["system_fingerprint"] = fp.strip()
        if schema_name is not None:
            resp_payload["schema_name"] = schema_name
        if isinstance(cl, str) and cl:
            resp_payload["call_label"] = cl
        if tl_tags is not None:
            resp_payload["llm_tags"] = tl_tags
        ha = transport.get("http_attempts")
        hs = transport.get("http_status")
        if isinstance(ha, int):
            resp_payload["http_attempts"] = ha
        if isinstance(hs, int):
            resp_payload["http_status"] = hs
        for ck in _CORRELATION_TRANSPORT_KEYS:
            if ck in transport:
                resp_payload[ck] = transport[ck]
        if self._log_mode == LogMode.full:
            resp_payload["content"] = content
        elif self._log_mode == LogMode.redacted:
            resp_payload["content_preview"] = content[:800]
        self._emit("llm_response", resp_payload)
        structured_meta: dict[str, Any] = {
            "latency_ms": dt_ms,
            "usage": usage,
            "finish_reason": finish_reason,
        }
        if isinstance(cid, str) and cid.strip():
            structured_meta["chat_completion_id"] = cid.strip()
        if isinstance(fp, str) and fp.strip():
            structured_meta["system_fingerprint"] = fp.strip()
        if isinstance(ha, int):
            structured_meta["http_attempts"] = ha
        if isinstance(hs, int):
            structured_meta["http_status"] = hs
        for ck in _CORRELATION_TRANSPORT_KEYS:
            if ck in transport:
                structured_meta[ck] = transport[ck]
        return content, effective, fingerprints, structured_meta

    def _emit_structured_output_failed(
        self,
        *,
        schema_name: str,
        stage: str,
        structured_output_mode: str,
        error: Exception,
        effective: dict[str, Any] | None = None,
        fingerprints: dict[str, str] | None = None,
        response_chars: int | None = None,
        validation_issues: list[dict[str, Any]] | None = None,
        validation_issue_count: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "state": self._state_getter(),
            "schema_name": schema_name,
            "stage": stage,
            "structured_output_mode": structured_output_mode,
            "error": self._serialize_error(error),
        }
        if effective is not None:
            payload["effective"] = effective
            ecl = effective.get("call_label")
            if isinstance(ecl, str) and ecl:
                payload["call_label"] = ecl
            etags = _top_level_llm_tags(effective)
            if etags is not None:
                payload["llm_tags"] = etags
        if fingerprints:
            payload.update(fingerprints)
        if response_chars is not None:
            payload["response_chars"] = response_chars
        if validation_issues is not None:
            payload["validation_issues"] = validation_issues
        if validation_issue_count is not None:
            payload["validation_issue_count"] = validation_issue_count
        if (
            validation_issues is not None
            and validation_issue_count is not None
            and validation_issue_count > len(validation_issues)
        ):
            payload["validation_issues_truncated"] = True
        self._emit("structured_output_failed", payload)

    @staticmethod
    def _native_response_format(model_type: type[T]) -> dict[str, Any]:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": model_type.__name__,
                "strict": True,
                "schema": model_type.model_json_schema(),
            },
        }

    def complete_text(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.0,
        top_p: float | None = None,
        frequency_penalty: float | None = None,
        presence_penalty: float | None = None,
        seed: int | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        provider: str | None = None,
        base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict[str, Any] | None = None,
        stop: list[str] | tuple[str, ...] | str | None = None,
        schema_name: str | None = None,
        response_format: Any = _RF_UNSET,
        http_retries: int | None = None,
        llm_tags: list[str] | tuple[str, ...] | str | None = None,
    ) -> str:
        sn = str(schema_name).strip() if schema_name is not None else None
        if response_format is _RF_UNSET:
            rf_resolved = self._defaults.get("response_format")
            rf_call = rf_resolved if isinstance(rf_resolved, dict) else None
        elif response_format is None:
            rf_call = None
        else:
            rf_call = _coerce_bridge_response_format(response_format)
        text, _effective, _fingerprints, _meta = self._request_text(
            messages=messages,
            model=model,
            temperature=temperature,
            top_p=top_p,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
            seed=seed,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            provider=provider,
            base_url=base_url,
            extra_headers=extra_headers,
            extra_body=extra_body,
            response_format=rf_call,
            stop=stop,
            schema_name=sn or None,
            http_retries=http_retries,
            llm_tags=llm_tags,
        )
        return text

    def parse(
        self,
        model_type: type[T],
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.0,
        top_p: float | None = None,
        frequency_penalty: float | None = None,
        presence_penalty: float | None = None,
        seed: int | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        provider: str | None = None,
        base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict[str, Any] | None = None,
        native_response_format: bool | None = None,
        stop: list[str] | tuple[str, ...] | str | None = None,
        http_retries: int | None = None,
        llm_tags: list[str] | tuple[str, ...] | str | None = None,
    ) -> T:
        use_native_response_format = (
            bool(self._defaults.get("native_response_format"))
            if native_response_format is None
            else native_response_format
        )
        structured_output_mode = "native_json_schema" if use_native_response_format else "prompt_only"
        schema_json = model_type.model_json_schema()
        schema_fingerprint = {"schema_sha256": _stable_json_sha256(schema_json)}
        schema_hint = json.dumps(schema_json, ensure_ascii=False)
        cap = self._client.settings.max_schema_json_chars
        if len(schema_hint) > cap:
            eff_pre, _, _, _ = self._merge_call(
                model=model,
                temperature=temperature,
                top_p=top_p,
                frequency_penalty=frequency_penalty,
                presence_penalty=presence_penalty,
                seed=seed,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
                provider=provider,
                base_url=base_url,
                extra_headers=extra_headers,
                extra_body=extra_body,
                stop=stop,
                http_retries=http_retries,
                llm_tags=llm_tags,
            )
            effective_schema_limit = {**eff_pre, "structured_output_mode": structured_output_mode}
            exc = ValueError(
                f"JSON Schema for {model_type.__name__!r} serializes to {len(schema_hint)} characters, "
                f"above max_schema_json_chars ({cap}); use a smaller model, split fields, or raise the limit "
                "on LLMSettings / env REPLAYT_LLM_MAX_SCHEMA_CHARS."
            )
            self._emit_structured_output_failed(
                schema_name=model_type.__name__,
                stage="schema_limit",
                structured_output_mode=structured_output_mode,
                error=exc,
                effective=effective_schema_limit,
                fingerprints=schema_fingerprint,
            )
            raise exc
        sys = (
            "You must respond with a single JSON object that validates against this JSON Schema "
            f"(return JSON only, no markdown):\n{schema_hint}"
        )
        full_messages = [{"role": "system", "content": sys}, *messages]
        response_format = self._native_response_format(model_type) if use_native_response_format else None
        text, effective, fingerprints, response_meta = self._request_text(
            messages=full_messages,
            model=model,
            temperature=temperature,
            top_p=top_p,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
            seed=seed,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            provider=provider,
            base_url=base_url,
            extra_headers=extra_headers,
            extra_body=extra_body,
            response_format=response_format,
            effective_extras={"structured_output_mode": structured_output_mode},
            schema_json=schema_json,
            schema_name=model_type.__name__,
            stop=stop,
            http_retries=http_retries,
            llm_tags=llm_tags,
        )
        cap = self._client.settings.max_parse_response_chars
        if len(text) > cap:
            exc = ValueError(
                f"Model response length ({len(text)} chars) exceeds max_parse_response_chars ({cap}); "
                "raise the limit on LLMSettings if needed."
            )
            self._emit_structured_output_failed(
                schema_name=model_type.__name__,
                stage="response_limit",
                structured_output_mode=structured_output_mode,
                error=exc,
                effective=effective,
                fingerprints=fingerprints,
                response_chars=len(text),
            )
            raise exc
        try:
            object_text = _extract_json_object(text, max_brace_starts=min(_MAX_JSON_OBJECT_BRACE_STARTS, cap))
        except Exception as exc:  # noqa: BLE001
            self._emit_structured_output_failed(
                schema_name=model_type.__name__,
                stage="json_extract",
                structured_output_mode=structured_output_mode,
                error=exc,
                effective=effective,
                fingerprints=fingerprints,
                response_chars=len(text),
            )
            raise
        try:
            obj = json.loads(object_text)
        except json.JSONDecodeError as exc:
            self._emit_structured_output_failed(
                schema_name=model_type.__name__,
                stage="json_decode",
                structured_output_mode=structured_output_mode,
                error=exc,
                effective=effective,
                fingerprints=fingerprints,
                response_chars=len(text),
            )
            raise
        try:
            result = model_type.model_validate(obj)
        except Exception as exc:  # noqa: BLE001
            val_log = _pydantic_validation_issues_for_log(exc)
            v_issues: list[dict[str, Any]] | None = None
            v_count: int | None = None
            if val_log is not None:
                v_issues, v_count = val_log
            self._emit_structured_output_failed(
                schema_name=model_type.__name__,
                stage="schema_validate",
                structured_output_mode=structured_output_mode,
                error=exc,
                effective=effective,
                fingerprints=fingerprints,
                response_chars=len(text),
                validation_issues=v_issues,
                validation_issue_count=v_count,
            )
            raise
        so_payload: dict[str, Any] = {
            "state": self._state_getter(),
            "schema_name": model_type.__name__,
            "data": result.model_dump(),
            "effective": effective,
            **fingerprints,
            **response_meta,
        }
        socl = effective.get("call_label")
        if isinstance(socl, str) and socl:
            so_payload["call_label"] = socl
        sotags = _top_level_llm_tags(effective)
        if sotags is not None:
            so_payload["llm_tags"] = sotags
        self._emit("structured_output", so_payload)
        return result
