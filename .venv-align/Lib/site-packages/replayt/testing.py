"""Helpers for deterministic tests: mock LLM responses and assert on run logs."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from typing import Any

from replayt.llm import LLMSettings, OpenAICompatClient
from replayt.persistence.base import EventStore
from replayt.runner import Runner, RunResult
from replayt.types import LogMode
from replayt.workflow import Workflow


def _fill_llm_transport_meta(transport_meta: dict[str, Any] | None) -> None:
    if transport_meta is None:
        return
    transport_meta.clear()
    transport_meta["http_attempts"] = 1
    transport_meta["http_status"] = 200


class DryRunLLMClient(OpenAICompatClient):
    """Returns placeholder responses without calling any LLM. Useful for ``replayt run --dry-run``.

    Structured responses are synthesized from the JSON Schema via a **minimal** filler: ``allOf`` /
    ``oneOf`` / ``anyOf`` and uncommon combinators are only partially handled. Complex schemas may
    not validate until you switch to :class:`MockLLMClient` or a real model.
    """

    def __init__(self, settings: LLMSettings | None = None) -> None:
        super().__init__(settings or LLMSettings(api_key="dry-run"))

    @classmethod
    def _minimal_json_from_schema(
        cls, schema: dict[str, Any], *, _defs: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Generate a minimal valid JSON object from a JSON Schema, including nested ``$ref``."""
        if _defs is None:
            _defs = schema.get("$defs", schema.get("definitions", {}))
        if "$ref" in schema:
            ref_path = schema["$ref"]
            ref_name = ref_path.rsplit("/", 1)[-1]
            ref_schema = _defs.get(ref_name, {})
            return cls._minimal_json_from_schema(ref_schema, _defs=_defs)
        if "allOf" in schema:
            merged: dict[str, Any] = {}
            for sub in schema["allOf"]:
                value = cls._minimal_value(sub, _defs)
                if isinstance(value, dict):
                    merged.update(value)
            if merged:
                return merged
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        result: dict[str, Any] = {}
        for key, prop in props.items():
            if key not in required:
                continue
            result[key] = cls._minimal_value(prop, _defs)
        return result

    @classmethod
    def _minimal_value(cls, prop: dict[str, Any], defs: dict[str, Any]) -> Any:
        if "const" in prop:
            return prop["const"]
        if "default" in prop:
            return prop["default"]
        if "$ref" in prop:
            ref_path = prop["$ref"]
            ref_name = ref_path.rsplit("/", 1)[-1]
            ref_schema = defs.get(ref_name, {})
            return cls._minimal_json_from_schema(ref_schema, _defs=defs)
        if "allOf" in prop:
            merged: dict[str, Any] = {}
            for sub in prop["allOf"]:
                merged.update(cls._minimal_value(sub, defs) if sub.get("$ref") or sub.get("properties") else {})
            return merged
        if "anyOf" in prop or "oneOf" in prop:
            variants = prop.get("anyOf") or prop.get("oneOf", [])
            if variants:
                return cls._minimal_value(variants[0], defs)
        typ = prop.get("type", "string")
        if isinstance(typ, list):
            typ = next((candidate for candidate in typ if candidate != "null"), typ[0] if typ else "string")
        if typ == "string":
            if "enum" in prop:
                return prop["enum"][0]
            min_length = max(int(prop.get("minLength", 0) or 0), 0)
            return "x" * min_length if min_length > 0 else ""
        if typ == "integer":
            return cls._minimal_number(prop, integer=True)
        if typ == "number":
            return cls._minimal_number(prop, integer=False)
        if typ == "boolean":
            return False
        if typ == "array":
            return cls._minimal_array(prop, defs)
        if typ == "object":
            if "properties" in prop:
                return cls._minimal_json_from_schema(prop, _defs=defs)
            return {}
        return ""

    @classmethod
    def _minimal_number(cls, prop: dict[str, Any], *, integer: bool) -> int | float:
        exclusive_min = prop.get("exclusiveMinimum")
        minimum = prop.get("minimum")
        multiple_of = prop.get("multipleOf")

        if integer:
            if exclusive_min is not None:
                value: int | float = math.floor(float(exclusive_min)) + 1
            elif minimum is not None:
                value = math.ceil(float(minimum))
            else:
                value = 0
        else:
            if exclusive_min is not None:
                value = float(exclusive_min) + 1.0
            elif minimum is not None:
                value = float(minimum)
            else:
                value = 0.0

        if multiple_of not in (None, 0):
            step = float(multiple_of)
            if step > 0:
                if value == 0:
                    value = step
                else:
                    value = math.ceil(float(value) / step) * step
                    if exclusive_min is not None and value <= float(exclusive_min):
                        value += step

        return int(value) if integer else float(value)

    @classmethod
    def _minimal_array(cls, prop: dict[str, Any], defs: dict[str, Any]) -> list[Any]:
        min_items = max(int(prop.get("minItems", 0) or 0), 0)
        prefix_items = prop.get("prefixItems")
        items = prop.get("items")
        out: list[Any] = []
        if isinstance(prefix_items, list):
            out.extend(cls._minimal_value(item, defs) if isinstance(item, dict) else "" for item in prefix_items)
        item_schema: dict[str, Any]
        if isinstance(items, dict):
            item_schema = items
        elif isinstance(prefix_items, list) and prefix_items:
            last_prefix = prefix_items[-1]
            item_schema = last_prefix if isinstance(last_prefix, dict) else {"type": "string"}
        else:
            item_schema = {"type": "string"}
        while len(out) < min_items:
            out.append(cls._minimal_value(item_schema, defs))
        return out

    @staticmethod
    def _schema_from_parse_prompt(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not messages:
            return None
        content = messages[0].get("content")
        if not isinstance(content, str):
            return None
        marker = "(return JSON only, no markdown):\n"
        if marker not in content:
            return None
        schema_text = content.split(marker, 1)[1].strip()
        try:
            schema = json.loads(schema_text)
        except json.JSONDecodeError:
            return None
        return schema if isinstance(schema, dict) else None

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
        _ = (
            model,
            temperature,
            top_p,
            frequency_penalty,
            presence_penalty,
            seed,
            max_tokens,
            timeout_seconds,
            base_url,
            extra_headers,
            extra_body,
            stop,
            http_retries,
        )
        content = "{}"
        if response_format and isinstance(response_format, dict):
            json_schema = response_format.get("json_schema", {})
            schema_body = json_schema.get("schema") if isinstance(json_schema, dict) else None
            if isinstance(schema_body, dict):
                content = json.dumps(self._minimal_json_from_schema(schema_body))
        else:
            schema = self._schema_from_parse_prompt(messages)
            if schema is not None:
                content = json.dumps(self._minimal_json_from_schema(schema))
        _fill_llm_transport_meta(transport_meta)
        return {
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


class MockLLMClient(OpenAICompatClient):
    """Queue fake ``/chat/completions`` JSON payloads (no network).

    Use :meth:`enqueue` with the assistant message **content** string (for ``complete_text`` /
    ``parse``, the content must be valid JSON when using :meth:`~replayt.llm.LLMBridge.parse`).
    """

    def __init__(self, settings: LLMSettings | None = None) -> None:
        super().__init__(settings or LLMSettings(api_key="test"))
        self._responses: list[dict[str, Any]] = []

    def enqueue(self, content: str, *, usage: dict[str, Any] | None = None) -> None:
        self._responses.append(
            {
                "choices": [{"message": {"content": content}}],
                "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0},
            }
        )

    def clear(self) -> None:
        self._responses.clear()

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
        _ = (
            messages,
            model,
            temperature,
            top_p,
            frequency_penalty,
            presence_penalty,
            seed,
            max_tokens,
            timeout_seconds,
            base_url,
            extra_headers,
            extra_body,
            response_format,
            stop,
            http_retries,
        )
        if not self._responses:
            raise RuntimeError("MockLLMClient: no queued response; call .enqueue(...) before running the workflow")
        _fill_llm_transport_meta(transport_meta)
        return self._responses.pop(0)


def run_with_mock(
    wf: Workflow,
    store: EventStore,
    mock: MockLLMClient,
    *,
    inputs: dict[str, Any] | None = None,
    run_id: str | None = None,
    resume: bool = False,
    log_mode: LogMode = LogMode.redacted,
) -> RunResult:
    """Run *wf* with a :class:`MockLLMClient` instead of calling a real provider."""

    runner = Runner(wf, store, log_mode=log_mode, llm_client=mock)
    return runner.run(inputs=inputs, run_id=run_id, resume=resume)


def assert_events(
    store: EventStore,
    run_id: str,
    event_type: str,
    *,
    predicate: Callable[[dict[str, Any]], bool] | None = None,
    min_count: int = 1,
) -> list[dict[str, Any]]:
    """Return events of *event_type* for *run_id*; raise ``AssertionError`` if too few match *predicate*."""

    raw = store.load_events(run_id)
    matching = [e for e in raw if e.get("type") == event_type]
    if predicate is not None:
        matching = [e for e in matching if predicate(e)]
    if len(matching) < min_count:
        raise AssertionError(
            f"expected at least {min_count} events of type {event_type!r}, found {len(matching)} (run_id={run_id!r})"
        )
    return matching
