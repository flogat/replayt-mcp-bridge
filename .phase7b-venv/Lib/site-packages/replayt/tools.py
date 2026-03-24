from __future__ import annotations

import inspect
import json
import logging
import re
from collections.abc import Callable
from typing import Any, TypeVar, get_type_hints

from pydantic import BaseModel, TypeAdapter

T = TypeVar("T")

_log = logging.getLogger("replayt.tools")

# OpenAI Chat Completions ``tools[].function.name`` (and most gateways): ASCII identifier-like, max 64.
_OPENAI_TOOL_FUNCTION_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
# Anthropic Messages API ``tools[].name`` allows a longer upper bound than OpenAI's 64.
_ANTHROPIC_TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

_UNSUPPORTED_PARAM_KINDS = frozenset(
    {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.VAR_POSITIONAL,
        inspect.Parameter.VAR_KEYWORD,
    }
)


def _optional_tool_call_id(value: Any) -> str | None:
    """Return a non-empty stripped string, or None if missing or not a string."""

    if not isinstance(value, str):
        return None
    s = value.strip()
    return s or None


def _openai_chat_tool_result_content(value: Any) -> str:
    """Stringify a tool return value for OpenAI Chat Completions ``role: "tool"`` message ``content``."""

    if isinstance(value, str):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _first_paragraph_doc(fn: Callable[..., Any]) -> str | None:
    raw = inspect.getdoc(fn)
    if not raw:
        return None
    para = raw.strip().split("\n\n", 1)[0].strip()
    return para or None


def _openai_parameters_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Build a JSON Schema object for OpenAI ``function.parameters`` from type hints."""

    sig = inspect.signature(fn)
    mod = inspect.getmodule(fn)
    globalns = vars(mod) if mod is not None else {}
    try:
        hints = get_type_hints(fn, globalns=globalns)
    except NameError:
        try:
            hints = get_type_hints(fn)
        except NameError as exc:
            msg = f"Could not resolve type hints for OpenAI tool schema: {fn.__name__!r}"
            raise TypeError(msg) from exc

    properties: dict[str, Any] = {}
    required: list[str] = []
    for param_name, param in sig.parameters.items():
        if param.kind in _UNSUPPORTED_PARAM_KINDS:
            msg = (
                f"Tool {fn.__name__!r}: parameter {param_name!r} is not supported for "
                "OpenAI tool schemas (use keyword-compatible parameters only)."
            )
            raise TypeError(msg)
        ann = hints.get(param_name, Any)
        properties[param_name] = TypeAdapter(ann).json_schema()
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    out: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        out["required"] = sorted(required)
    return out


class ToolRegistry:
    """Registers typed callables and records tool_call / tool_result events."""

    def __init__(
        self,
        emit: Callable[[str, dict[str, Any]], None],
        state_getter: Callable[[], str | None],
    ) -> None:
        self._emit = emit
        self._state_getter = state_getter
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, fn: Callable[..., T]) -> Callable[..., T]:
        self._tools[fn.__name__] = fn
        return fn

    def openai_chat_tools(self) -> list[dict[str, Any]]:
        """OpenAI Chat Completions ``tools`` payloads for registered handlers (composition helper).

        Each entry matches ``{"type": "function", "function": {"name", "parameters", ...}}``.
        Parameter JSON Schemas come from Pydantic :class:`~pydantic.TypeAdapter` (same hints as
        :meth:`call`). Docstrings supply ``function.description`` (first paragraph only).

        This does **not** route model tool calls through :class:`~replayt.llm.LLMBridge`; call the
        vendor SDK inside one ``@wf.step``, pass this list as ``tools=``, then execute chosen calls
        through :meth:`call` so ``tool_call`` / ``tool_result`` lines stay in JSONL.
        """

        out: list[dict[str, Any]] = []
        for name in sorted(self._tools):
            if not _OPENAI_TOOL_FUNCTION_NAME_RE.fullmatch(name):
                msg = (
                    f"Tool name {name!r} is not valid for OpenAI Chat Completions "
                    "(use 1-64 characters: ASCII letters, digits, underscore, or hyphen only)."
                )
                raise ValueError(msg)
            fn = self._tools[name]
            func: dict[str, Any] = {"name": name, "parameters": _openai_parameters_schema(fn)}
            desc = _first_paragraph_doc(fn)
            if desc:
                func["description"] = desc
            out.append({"type": "function", "function": func})
        return out

    def anthropic_messages_tools(self) -> list[dict[str, Any]]:
        """Anthropic Messages API ``tools`` payloads for registered handlers (composition helper).

        Each entry matches ``{"name", "input_schema", ...}`` with ``input_schema`` as the JSON object
        schema derived from the handler's type hints (the same shapes as OpenAI
        ``function.parameters`` from :meth:`openai_chat_tools`).
        Docstrings supply ``description`` (first paragraph only) when present.

        Pair with :meth:`apply_anthropic_tool_use_blocks` inside a vendor SDK ``@wf.step`` so
        ``tool_use`` blocks still execute through :meth:`call` and emit replayt ``tool_call`` /
        ``tool_result`` lines.
        """

        out: list[dict[str, Any]] = []
        for name in sorted(self._tools):
            if not _ANTHROPIC_TOOL_NAME_RE.fullmatch(name):
                msg = (
                    f"Tool name {name!r} is not valid for Anthropic Messages tools "
                    "(use 1-128 characters: ASCII letters, digits, underscore, or hyphen only)."
                )
                raise ValueError(msg)
            fn = self._tools[name]
            row: dict[str, Any] = {"name": name, "input_schema": _openai_parameters_schema(fn)}
            desc = _first_paragraph_doc(fn)
            if desc:
                row["description"] = desc
            out.append(row)
        return out

    def bedrock_converse_tools(self) -> list[dict[str, Any]]:
        """Amazon Bedrock Converse API ``toolConfig["tools"]`` entries (composition helper).

        Each element matches ``{"toolSpec": {"name", "inputSchema": {"json": ...}, ...}}``
        where ``inputSchema.json`` is the JSON object schema from handler type hints (the
        same shapes as OpenAI ``function.parameters`` from :meth:`openai_chat_tools`).
        Docstrings supply ``toolSpec.description`` (first paragraph only) when present.

        Bedrock constrains tool names to the same 1-64 character pattern as OpenAI Chat
        function names; longer Anthropic-only names must be registered under an alias or
        declared beside the Bedrock SDK without this helper.

        Pair with :meth:`apply_bedrock_converse_tool_use_blocks` on assistant ``content``
        from ``converse`` / ``converse_stream`` so invocations still go through
        :meth:`call` and emit replayt ``tool_call`` / ``tool_result`` lines.
        """

        out: list[dict[str, Any]] = []
        for name in sorted(self._tools):
            if not _OPENAI_TOOL_FUNCTION_NAME_RE.fullmatch(name):
                msg = (
                    f"Tool name {name!r} is not valid for Amazon Bedrock Converse tools "
                    "(use 1-64 characters: ASCII letters, digits, underscore, or hyphen only)."
                )
                raise ValueError(msg)
            fn = self._tools[name]
            spec: dict[str, Any] = {
                "name": name,
                "inputSchema": {"json": _openai_parameters_schema(fn)},
            }
            desc = _first_paragraph_doc(fn)
            if desc:
                spec["description"] = desc
            out.append({"toolSpec": spec})
        return out

    def apply_anthropic_tool_use_blocks(
        self,
        content: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    ) -> list[Any]:
        """Run Anthropic Messages ``tool_use`` blocks through :meth:`call` in content list order.

        Each element should be a mapping with ``type == "tool_use"``, a non-empty ``name``, and an
        ``input`` object (dict). Other block types (for example ``text``) are skipped; results are
        returned **only** for ``tool_use`` blocks, in the order they appear. When a block carries a
        non-empty string ``id``, it is copied to optional ``tool_call_id`` on emitted
        ``tool_call`` / ``tool_result`` lines.

        This is a thin composition helper for ``anthropic`` SDK steps: pass
        ``message.content`` (or a filtered list of blocks) after ``messages.create``, then feed
        tool results back to the API with ``role: user`` tool_result blocks as usual.
        """

        if not content:
            return []
        results: list[Any] = []
        for i, block in enumerate(content):
            if not isinstance(block, dict):
                msg = f"content[{i}]: expected dict, got {type(block).__name__}"
                raise TypeError(msg)
            if block.get("type") != "tool_use":
                continue
            name = block.get("name")
            if not isinstance(name, str) or not name.strip():
                msg = f"content[{i}]: tool_use missing or invalid name"
                raise ValueError(msg)
            raw_input = block.get("input", {})
            if isinstance(raw_input, str):
                stripped = raw_input.strip()
                if not stripped:
                    args: dict[str, Any] = {}
                else:
                    try:
                        args = json.loads(stripped)
                    except json.JSONDecodeError as exc:
                        msg = f"content[{i}]: invalid JSON in tool_use.input: {exc.msg}"
                        raise ValueError(msg) from exc
            elif isinstance(raw_input, dict):
                args = raw_input
            else:
                msg = (
                    f"content[{i}]: tool_use.input must be str or dict, "
                    f"got {type(raw_input).__name__}"
                )
                raise TypeError(msg)
            if not isinstance(args, dict):
                msg = f"content[{i}]: decoded tool_use.input must be a JSON object"
                raise TypeError(msg)
            bid = _optional_tool_call_id(block.get("id"))
            results.append(self.call(name, args, tool_call_id=bid))
        return results

    def apply_bedrock_converse_tool_use_blocks(
        self,
        content: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    ) -> list[Any]:
        """Run Bedrock Converse ``toolUse`` content blocks through :meth:`call` in list order.

        Each element should be a Converse **ContentBlock** mapping (as returned by boto3):
        a ``toolUse`` object with non-empty ``name`` and ``input`` (JSON object, or a JSON
        object string). Other blocks (``text``, ``image``, and similar) are skipped;
        results are returned **only** for ``toolUse`` blocks, in the order they appear.

        When ``toolUse`` includes a non-empty string ``toolUseId``, it is copied to optional
        ``tool_call_id`` on emitted ``tool_call`` / ``tool_result`` lines so you can pair results
        when sending ``toolResult`` blocks back to Bedrock.
        """

        if not content:
            return []
        results: list[Any] = []
        for i, block in enumerate(content):
            if not isinstance(block, dict):
                msg = f"content[{i}]: expected dict, got {type(block).__name__}"
                raise TypeError(msg)
            tu = block.get("toolUse")
            if tu is None:
                continue
            if not isinstance(tu, dict):
                msg = f"content[{i}]: toolUse must be a dict, got {type(tu).__name__}"
                raise TypeError(msg)
            name = tu.get("name")
            if not isinstance(name, str) or not name.strip():
                msg = f"content[{i}]: toolUse missing or invalid name"
                raise ValueError(msg)
            raw_input = tu.get("input", {})
            if isinstance(raw_input, str):
                stripped = raw_input.strip()
                if not stripped:
                    args = {}
                else:
                    try:
                        args = json.loads(stripped)
                    except json.JSONDecodeError as exc:
                        msg = f"content[{i}]: invalid JSON in toolUse.input: {exc.msg}"
                        raise ValueError(msg) from exc
            elif isinstance(raw_input, dict):
                args = raw_input
            else:
                msg = (
                    f"content[{i}]: toolUse.input must be str or dict, "
                    f"got {type(raw_input).__name__}"
                )
                raise TypeError(msg)
            if not isinstance(args, dict):
                msg = f"content[{i}]: decoded toolUse.input must be a JSON object"
                raise TypeError(msg)
            uid = _optional_tool_call_id(tu.get("toolUseId"))
            results.append(self.call(name, args, tool_call_id=uid))
        return results

    def apply_openai_chat_tool_calls(
        self,
        tool_calls: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    ) -> list[Any]:
        """Run OpenAI Chat Completions ``tool_calls`` through :meth:`call` in API list order.

        Each element should match the JSON shape returned by the API: a mapping with
        ``type == "function"`` and a nested ``function`` object containing ``name`` and
        ``arguments``. ``arguments`` may be a JSON object string or already a ``dict``.

        This is a thin composition helper for vendor SDK steps: pair with
        :meth:`openai_chat_tools` when building ``tools=``, then pass
        ``message.tool_calls`` converted with ``model_dump()`` (or equivalent) so each
        model-chosen invocation still emits replayt ``tool_call`` / ``tool_result`` lines.
        When an entry includes a non-empty string ``id`` (OpenAI tool call id), it is copied to
        optional ``tool_call_id`` on those JSONL payloads.

        Returns one result per tool call (same order as ``tool_calls``).
        """

        if not tool_calls:
            return []
        results: list[Any] = []
        for i, tc in enumerate(tool_calls):
            if not isinstance(tc, dict):
                msg = f"tool_calls[{i}]: expected dict, got {type(tc).__name__}"
                raise TypeError(msg)
            if tc.get("type") != "function":
                msg = f"tool_calls[{i}]: expected type 'function', got {tc.get('type')!r}"
                raise ValueError(msg)
            fn = tc.get("function")
            if not isinstance(fn, dict):
                msg = f"tool_calls[{i}]: function must be a dict, got {type(fn).__name__}"
                raise TypeError(msg)
            name = fn.get("name")
            if not isinstance(name, str) or not name.strip():
                msg = f"tool_calls[{i}]: missing or invalid function.name"
                raise ValueError(msg)
            raw_args = fn.get("arguments", "{}")
            if isinstance(raw_args, str):
                stripped = raw_args.strip()
                if not stripped:
                    args = {}
                else:
                    try:
                        args = json.loads(stripped)
                    except json.JSONDecodeError as exc:
                        msg = f"tool_calls[{i}]: invalid JSON in function.arguments: {exc.msg}"
                        raise ValueError(msg) from exc
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                msg = (
                    f"tool_calls[{i}]: function.arguments must be str or dict, "
                    f"got {type(raw_args).__name__}"
                )
                raise TypeError(msg)
            if not isinstance(args, dict):
                msg = f"tool_calls[{i}]: decoded arguments must be a JSON object"
                raise TypeError(msg)
            oid = _optional_tool_call_id(tc.get("id"))
            results.append(self.call(name, args, tool_call_id=oid))
        return results

    def openai_chat_tool_result_messages(
        self,
        tool_calls: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
        results: list[Any] | tuple[Any, ...] | None,
    ) -> list[dict[str, Any]]:
        """Build OpenAI Chat Completions ``messages`` entries with ``role: "tool"`` for the next turn.

        After :meth:`apply_openai_chat_tool_calls`, append the assistant message (with ``tool_calls``)
        plus these rows before calling ``chat.completions.create`` again. Each element of
        ``tool_calls`` must match the vendor shape (same as :meth:`apply_openai_chat_tool_calls`) and
        include a non-empty string ``id``; OpenAI rejects follow-up turns without ``tool_call_id``.

        ``results`` must have the same length as ``tool_calls`` (typically the list returned by
        :meth:`apply_openai_chat_tool_calls`). Non-string values are JSON-encoded (sorted object keys;
        :class:`~pydantic.BaseModel` results use :meth:`~pydantic.BaseModel.model_dump_json`).

        This is a pure message-shaping helper: it does not emit JSONL or invoke tools.
        """

        if not tool_calls:
            if results:
                raise ValueError("openai_chat_tool_result_messages: results given but tool_calls is empty")
            return []
        if results is None:
            raise ValueError("openai_chat_tool_result_messages: results is required when tool_calls is non-empty")
        if len(tool_calls) != len(results):
            raise ValueError(
                "openai_chat_tool_result_messages: tool_calls and results must have the same length "
                f"(got {len(tool_calls)} vs {len(results)})"
            )
        out: list[dict[str, Any]] = []
        for i, (tc, res) in enumerate(zip(tool_calls, results, strict=True)):
            if not isinstance(tc, dict):
                msg = f"tool_calls[{i}]: expected dict, got {type(tc).__name__}"
                raise TypeError(msg)
            tcid = _optional_tool_call_id(tc.get("id"))
            if not tcid:
                msg = (
                    f"tool_calls[{i}]: missing non-empty string id "
                    "(OpenAI requires tool_call_id on each tool message)"
                )
                raise ValueError(msg)
            out.append({"role": "tool", "tool_call_id": tcid, "content": _openai_chat_tool_result_content(res)})
        return out

    def call(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        tool_call_id: str | None = None,
    ) -> Any:
        """Invoke a registered tool, emitting ``tool_call`` / ``tool_result`` events.

        Optional ``tool_call_id`` (non-empty after strip) is copied onto both payloads so vendor
        multi-turn tool protocols (OpenAI, Anthropic, Bedrock, or custom gateways) can be replayed
        from JSONL without losing per-invocation ids.
        """

        if not isinstance(arguments, dict):
            raise TypeError("arguments must be a dict")
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        fn = self._tools[name]
        state = self._state_getter()
        if tool_call_id is not None and not isinstance(tool_call_id, str):
            msg = "tool_call_id must be str or None"
            raise TypeError(msg)
        tcid = _optional_tool_call_id(tool_call_id)
        call_payload: dict[str, Any] = {"state": state, "name": name, "arguments": arguments}
        if tcid:
            call_payload["tool_call_id"] = tcid
        self._emit("tool_call", call_payload)
        try:
            sig = inspect.signature(fn)
            mod = inspect.getmodule(fn)
            globalns = vars(mod) if mod is not None else {}
            try:
                hints = get_type_hints(fn, globalns=globalns)
            except NameError:
                try:
                    hints = get_type_hints(fn)
                except NameError:
                    _log.warning(
                        "Could not resolve type hints for tool %r; validating arguments as Any",
                        name,
                    )
                    hints = {p: Any for p in sig.parameters}
            unknown = set(arguments) - set(sig.parameters)
            if unknown:
                raise TypeError(f"Unexpected tool arguments: {sorted(unknown)}")

            bound: dict[str, Any] = {}
            for param_name, param in sig.parameters.items():
                if param.kind not in {
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                }:
                    raise TypeError(f"Unsupported tool parameter kind for {param_name}: {param.kind}")
                if param_name not in arguments:
                    if param.default is inspect.Parameter.empty:
                        raise TypeError(f"Missing tool argument: {param_name}")
                    continue
                raw = arguments[param_name]
                ann = hints.get(param_name, Any)
                if ann is Any:
                    bound[param_name] = raw
                elif isinstance(ann, type) and issubclass(ann, BaseModel):
                    bound[param_name] = ann.model_validate(raw)
                else:
                    bound[param_name] = TypeAdapter(ann).validate_python(raw)
            result = fn(**bound)
            out: Any = result
            if isinstance(result, BaseModel):
                out = result.model_dump()
            ok_payload: dict[str, Any] = {
                "state": state,
                "name": name,
                "ok": True,
                "result": out,
                "error": None,
            }
            if tcid:
                ok_payload["tool_call_id"] = tcid
            self._emit("tool_result", ok_payload)
            return result
        except Exception as e:  # noqa: BLE001
            err_payload: dict[str, Any] = {
                "state": state,
                "name": name,
                "ok": False,
                "result": None,
                "error": {"type": e.__class__.__name__, "message": str(e)},
            }
            if tcid:
                err_payload["tool_call_id"] = tcid
            self._emit("tool_result", err_payload)
            raise
