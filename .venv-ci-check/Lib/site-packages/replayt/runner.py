from __future__ import annotations

import copy
import html as _html
import json
import logging
import time
import traceback
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from replayt.exceptions import ApprovalPending, ContextSchemaError, ReplaytError, RunFailed
from replayt.llm import LLMBridge, LLMSettings, OpenAICompatClient
from replayt.persistence.base import EventStore
from replayt.security import (
    approval_reason_missing,
    missing_actor_fields,
    normalize_name_list,
    redact_named_fields,
    sanitize_base_url_for_output,
    trust_boundary_checks,
)
from replayt.tools import ToolRegistry
from replayt.types import LogMode
from replayt.workflow import Workflow

_log = logging.getLogger("replayt.runner")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_error(exc: Exception, *, include_traceback: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": exc.__class__.__name__,
        "module": exc.__class__.__module__,
        "message": str(exc),
    }
    if include_traceback:
        payload["traceback"] = "".join(traceback.format_exception(exc)).rstrip()
    return payload


def _validate_context_serializable(data: dict[str, Any]) -> None:
    """Warn about context values that will be silently degraded by JSON serialization."""
    for key, value in data.items():
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            _log.warning(
                "Context key %r has non-JSON-serializable value of type %s; "
                "it will be converted via str() during persistence and may lose fidelity on resume",
                key,
                type(value).__name__,
            )


@dataclass
class RunResult:
    run_id: str
    status: str  # completed | failed | paused
    final_state: str | None = None
    error: str | None = None

    def _repr_html_(self) -> str:
        status_colors = {
            "completed": ("#065f46", "#d1fae5"),
            "failed": ("#991b1b", "#fee2e2"),
            "paused": ("#854d0e", "#fef9c3"),
        }
        fg, bg = status_colors.get(self.status, ("#374151", "#f3f4f6"))
        esc = _html.escape
        parts = [
            '<div style="font-family:system-ui,sans-serif;border:1px solid #e5e7eb;border-radius:8px;'
            'padding:12px 16px;max-width:420px;background:#fff;">',
            f'<div style="font-size:13px;color:#6b7280;margin-bottom:4px;">run_id: '
            f"<code>{esc(self.run_id)}</code></div>",
            f'<div style="margin-bottom:4px;">'
            f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;'
            f'font-weight:600;color:{fg};background:{bg};">{esc(self.status)}</span></div>',
        ]
        if self.final_state is not None:
            parts.append(
                f'<div style="font-size:13px;color:#374151;">final_state: '
                f"<strong>{esc(self.final_state)}</strong></div>"
            )
        if self.error:
            parts.append(
                f'<div style="font-size:13px;color:#991b1b;margin-top:4px;">error: {esc(self.error)}</div>'
            )
        parts.append("</div>")
        return "".join(parts)


class RunContext:
    """Mutable per-run bag + LLM/tools facades."""

    def __init__(self, runner: Runner, *, llm_defaults: dict[str, Any] | None = None) -> None:
        self._runner = runner
        self.run_id = runner.run_id
        self.workflow_name = runner.workflow.name
        self.data: dict[str, Any] = {}
        self.llm = LLMBridge(
            emit=runner._emit_payload,
            client=runner._llm_client,
            log_mode=runner.log_mode,
            state_getter=lambda: runner._current_state,
            defaults=llm_defaults,
        )
        self.tools = ToolRegistry(emit=runner._emit_payload, state_getter=lambda: runner._current_state)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def note(
        self,
        kind: str,
        *,
        summary: str | None = None,
        data: Any = None,
    ) -> None:
        """Append a small, explicit application note for the current state."""

        note_kind = str(kind).strip()
        if not note_kind:
            raise ValueError("note kind must be a non-empty string")
        payload: dict[str, Any] = {
            "state": self._runner._current_state,
            "kind": note_kind,
        }
        if summary is not None:
            payload["summary"] = str(summary)
        if data is not None:
            payload["data"] = data
        self._runner._emit_payload("step_note", payload)

    def request_approval(
        self,
        approval_id: str,
        *,
        summary: str,
        details: dict[str, Any] | None = None,
        on_approve: str | None = None,
        on_reject: str | None = None,
    ) -> None:
        self._runner._emit_payload(
            "approval_requested",
            {
                "approval_id": approval_id,
                "state": self._runner._current_state,
                "summary": summary,
                "details": details or {},
                "on_approve": on_approve,
                "on_reject": on_reject,
            },
        )
        raise ApprovalPending(
            approval_id,
            summary=summary,
            details=details,
            on_approve=on_approve,
            on_reject=on_reject,
        )

    def is_approved(self, approval_id: str) -> bool:
        return self._runner._approval_outcomes.get(str(approval_id)) is True

    def is_rejected(self, approval_id: str) -> bool:
        return self._runner._approval_outcomes.get(str(approval_id)) is False


class Runner:
    """Execute a workflow against a store, emitting structured events.

    .. warning::
        ``Runner`` is **not thread-safe**. Each concurrent run must use its own
        ``Runner`` instance because per-run state (``run_id``, ``_current_state``,
        approval outcome map) is stored on the instance and mutated during ``run()``.

    **Terminal failure events:** On failure the store records a ``run_failed`` event
    (payload includes structured ``error`` and ``state``), then a final
    ``run_completed`` with ``status: "failed"``. Use ``run_failed`` for diagnostics;
    use ``run_completed`` for uniform end-of-run detection (same event type as success).

    **Approval IDs** are compared as strings after coercion; use stable string IDs in workflows.

    **Lifecycle hooks:** Optional ``before_step`` / ``after_step`` run in the same process as the workflow
    (after context schema checks / after a successful handler return, respectively). They are for explicit
    side effects (metrics, trace IDs, notifications), not a parallel control-flow mechanism; keep transitions
    in step code.
    """

    _DEFAULT_MAX_STEPS = 200

    def __init__(
        self,
        workflow: Workflow,
        store: EventStore,
        *,
        llm_settings: LLMSettings | None = None,
        log_mode: LogMode = LogMode.redacted,
        llm_client: OpenAICompatClient | None = None,
        include_tracebacks: bool = False,
        max_steps: int | None = None,
        before_step: Callable[[RunContext, str], None] | None = None,
        after_step: Callable[[RunContext, str, str | None], None] | None = None,
        redact_keys: list[str] | tuple[str, ...] | None = None,
        policy_hooks: dict[str, Any] | None = None,
    ) -> None:
        self.workflow = workflow
        self.store = store
        self.log_mode = log_mode
        self.redact_keys = normalize_name_list(redact_keys)
        self.include_tracebacks = include_tracebacks
        self.max_steps = max_steps if max_steps is not None else self._DEFAULT_MAX_STEPS
        if self.max_steps < 1:
            raise ValueError("max_steps must be >= 1")
        self._owns_client = llm_client is None
        self._llm_client = llm_client or OpenAICompatClient(llm_settings or LLMSettings.from_env())
        self.run_id: str = ""
        self._current_state: str | None = None
        # approval_id -> True (approved) / False (rejected); last resolution wins when replaying events
        self._approval_outcomes: dict[str, bool] = {}
        #: Called after context schema checks pass and before the step handler (once per state visit, not per retry).
        self._before_step = before_step
        #: Called after a successful handler return, before ``state_exited`` / ``transition`` events.
        self._after_step = after_step
        self._policy_hooks = copy.deepcopy(policy_hooks) if policy_hooks else None

    def close(self) -> None:
        if self._owns_client:
            self._llm_client.close()

    def __enter__(self) -> Runner:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _emit_payload(self, typ: str, payload: dict[str, Any]) -> None:
        event_payload = payload
        if self.redact_keys:
            event_payload = redact_named_fields(payload, field_names=self.redact_keys)
        self.store.append_event(self.run_id, ts=_utcnow_iso(), typ=typ, payload=event_payload)

    def _runtime_snapshot(self) -> dict[str, Any]:
        settings = getattr(self._llm_client, "settings", None)
        contract = self.workflow.contract()
        llm_payload: dict[str, Any] = {"client_class": type(self._llm_client).__name__}
        trust_checks = trust_boundary_checks(base_url=None, log_mode=self.log_mode)
        if isinstance(settings, LLMSettings):
            llm_payload.update(
                {
                    "provider": settings.provider,
                    "base_url": sanitize_base_url_for_output(settings.base_url),
                    "model": settings.model,
                    "timeout_seconds": settings.timeout_seconds,
                    "top_p": settings.top_p,
                    "frequency_penalty": settings.frequency_penalty,
                    "presence_penalty": settings.presence_penalty,
                    "seed": settings.seed,
                    "max_tokens": settings.max_tokens,
                    "stop": list(settings.stop) if settings.stop else None,
                    "extra_body_keys": sorted((settings.extra_body or {}).keys()),
                    "max_response_bytes": settings.max_response_bytes,
                    "http_retries": settings.http_retries,
                    "max_parse_response_chars": settings.max_parse_response_chars,
                    "max_schema_json_chars": settings.max_schema_json_chars,
                    "extra_header_names": sorted((settings.extra_headers or {}).keys()),
                    "api_key_present": bool(settings.api_key),
                }
            )
            trust_checks = trust_boundary_checks(base_url=settings.base_url, log_mode=self.log_mode)
        runtime = {
            "engine": {
                "log_mode": self.log_mode.value,
                "max_steps": self.max_steps,
                "redact_keys": list(self.redact_keys),
            },
            "hooks": {
                "before_step": self._before_step is not None,
                "after_step": self._after_step is not None,
            },
            "store": {
                "class": type(self.store).__name__,
            },
            "workflow": {
                "contract_schema": contract["schema"],
                "contract_sha256": contract["contract_sha256"],
            },
            "llm": llm_payload,
            "trust_boundary": {
                "warnings": [check.detail for check in trust_checks if not check.ok],
            },
        }
        if self._policy_hooks:
            runtime["policy_hooks"] = copy.deepcopy(self._policy_hooks)
        return runtime

    def _load_approval_state_from_events(self, events: list[dict[str, Any]]) -> None:
        self._approval_outcomes.clear()
        for e in events:
            if e.get("type") == "approval_resolved":
                p = e.get("payload") or {}
                aid = p.get("approval_id")
                if aid is None:
                    continue
                self._approval_outcomes[str(aid)] = bool(p.get("approved"))

    def _replay_context_data(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for e in events:
            if e.get("type") == "context_snapshot":
                p = e.get("payload") or {}
                snap = p.get("data") or {}
                if isinstance(snap, dict):
                    data = dict(snap)
        return data

    def _last_snapshot_state(self, events: list[dict[str, Any]]) -> str | None:
        last: str | None = None
        for e in events:
            if e.get("type") == "context_snapshot":
                p = e.get("payload") or {}
                last = str(p.get("state")) if p.get("state") is not None else last
        return last

    def _resume_target_from_events(self, events: list[dict[str, Any]]) -> tuple[str | None, str | None]:
        """Pair each ``approval_resolved`` with the oldest still-pending request for that id (FIFO)."""

        pending: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        paired: list[tuple[bool, dict[str, Any]]] = []
        for e in events:
            payload = e.get("payload") or {}
            typ = e.get("type")
            if typ == "approval_requested":
                aid = payload.get("approval_id")
                if aid is not None:
                    pending[str(aid)].append(payload)
            elif typ == "approval_resolved":
                aid = payload.get("approval_id")
                if aid is None:
                    continue
                q = pending[str(aid)]
                if q:
                    req = q.popleft()
                    paired.append((bool(payload.get("approved")), req))
        if not paired:
            return None, None
        approved, request = paired[-1]
        target = request.get("on_approve") if approved else request.get("on_reject")
        if target in (None, ""):
            return None, str(request.get("state")) if request.get("state") is not None else None
        return str(target), str(request.get("state")) if request.get("state") is not None else None

    def run(
        self,
        *,
        inputs: dict[str, Any] | None = None,
        run_id: str | None = None,
        resume: bool = False,
        tags: dict[str, str] | None = None,
        run_metadata: dict[str, Any] | None = None,
        experiment: dict[str, Any] | None = None,
    ) -> RunResult:
        if not self.workflow.initial_state:
            raise RuntimeError("Workflow.initial_state is not set (call set_initial)")

        self.run_id = run_id or str(uuid.uuid4())
        self._approval_outcomes.clear()
        self._current_state = None
        if resume and not run_id:
            raise ValueError("run_id is required when resume=True")
        events = self.store.load_events(self.run_id) if resume else []
        if resume and not events:
            raise RuntimeError(f"No events found for run_id={self.run_id!r}")
        if resume:
            self._load_approval_state_from_events(events)

        start_state = self.workflow.initial_state
        ctx_data: dict[str, Any] = {}
        paused_from_state: str | None = None
        if resume and events:
            ctx_data = self._replay_context_data(events)
            target_state, paused_from_state = self._resume_target_from_events(events)
            if target_state is not None:
                start_state = target_state
            else:
                snapped = self._last_snapshot_state(events)
                if snapped is not None:
                    start_state = snapped

        if not resume:
            started_payload: dict[str, Any] = {
                "workflow_name": self.workflow.name,
                "workflow_version": self.workflow.version,
                "initial_state": self.workflow.initial_state,
                "inputs": inputs or {},
                "runtime": self._runtime_snapshot(),
            }
            if self.workflow.meta:
                meta_out = dict(self.workflow.meta)
                meta_out.pop("llm_defaults", None)
                if meta_out:
                    started_payload["workflow_meta"] = meta_out
            if tags:
                started_payload["tags"] = tags
            if run_metadata:
                started_payload["run_metadata"] = run_metadata
            if experiment:
                started_payload["experiment"] = dict(experiment)
            self._emit_payload("run_started", started_payload)
        elif paused_from_state is not None and start_state != paused_from_state:
            self._emit_payload(
                "approval_applied",
                {
                    "approval_state": paused_from_state,
                    "resumed_at_state": start_state,
                },
            )
            self._emit_payload(
                "transition",
                {"from_state": paused_from_state, "to_state": start_state, "reason": "approval_resolved"},
            )

        merged_llm: dict[str, Any] = {}
        if self.workflow.llm_defaults:
            merged_llm.update(self.workflow.llm_defaults)
        meta_ld = (self.workflow.meta or {}).get("llm_defaults")
        if isinstance(meta_ld, dict):
            merged_llm.update(meta_ld)
        if experiment:
            prev_exp = merged_llm.get("experiment")
            if isinstance(prev_exp, dict):
                merged_llm["experiment"] = {**prev_exp, **dict(experiment)}
            else:
                merged_llm["experiment"] = dict(experiment)
        ctx = RunContext(self, llm_defaults=merged_llm or None)
        ctx.data.update(ctx_data)
        if inputs is not None and not resume:
            ctx.data.update(inputs)

        state: str | None = start_state
        steps_taken = 0
        try:
            while state is not None:
                steps_taken += 1
                if steps_taken > self.max_steps:
                    err_msg = (
                        f"Run exceeded max_steps={self.max_steps} "
                        f"(last state: {state!r}). Possible infinite loop."
                    )
                    exc = RunFailed(err_msg)
                    err_detail = _serialize_error(exc, include_traceback=self.include_tracebacks)
                    self._emit_payload("step_error", {"state": state, "error": err_detail})
                    self._emit_payload("run_failed", {"error": err_detail, "state": state})
                    raise exc
                self._current_state = state
                handler = self.workflow.get_handler(state)
                policy = self.workflow.retry_policy_for(state)

                self._emit_payload("state_entered", {"state": state})

                expects = self.workflow.expects_for(state)
                if expects:
                    violations: list[str] = []
                    for key, expected_type in expects.items():
                        if key not in ctx.data:
                            violations.append(f"missing key {key!r}")
                        elif expected_type is not object:
                            value = ctx.data[key]
                            if not isinstance(value, expected_type):
                                violations.append(
                                    f"key {key!r}: expected {expected_type.__name__}, "
                                    f"got {type(value).__name__}"
                                )
                    if violations:
                        schema_err = ContextSchemaError(state, violations)
                        err_detail = _serialize_error(
                            schema_err, include_traceback=self.include_tracebacks
                        )
                        self._emit_payload("step_error", {"state": state, "error": err_detail})
                        self._emit_payload("run_failed", {"error": err_detail, "state": state})
                        raise RunFailed(str(schema_err)) from schema_err

                if self._before_step is not None:
                    self._before_step(ctx, state)

                next_state: str | None = None
                last_err: Exception | None = None
                for attempt in range(1, policy.max_attempts + 1):
                    try:
                        next_state = handler(ctx)
                        if not self.workflow.allows_transition(state, next_state):
                            allowed = [dst for src, dst in self.workflow.edges() if src == state]
                            raise RuntimeError(
                                f"Step {state!r} returned undeclared transition {next_state!r}; allowed={allowed}"
                            )
                        last_err = None
                        break
                    except ApprovalPending as approval:
                        _validate_context_serializable(ctx.data)
                        try:
                            snapshot_data = copy.deepcopy(ctx.data)
                        except Exception:  # noqa: BLE001
                            _log.warning(
                                "deepcopy failed for context snapshot in state %r; "
                                "falling back to shallow copy (non-copyable values may share references)",
                                state,
                            )
                            snapshot_data = dict(ctx.data)
                        self._emit_payload(
                            "context_snapshot",
                            {"state": state, "data": snapshot_data},
                        )
                        self._emit_payload(
                            "run_paused",
                            {
                                "reason": "approval_required",
                                "approval_id": approval.approval_id,
                                "on_approve": approval.on_approve,
                                "on_reject": approval.on_reject,
                            },
                        )
                        return RunResult(self.run_id, "paused", final_state=state)
                    except ReplaytError as e:
                        next_state = None
                        last_err = e
                        break
                    except Exception as e:  # noqa: BLE001
                        next_state = None
                        last_err = e
                        if attempt >= policy.max_attempts:
                            break
                        self._emit_payload(
                            "retry_scheduled",
                            {
                                "state": state,
                                "attempt": attempt,
                                "max_attempts": policy.max_attempts,
                                "error": _serialize_error(e, include_traceback=self.include_tracebacks),
                            },
                        )
                        if policy.backoff_seconds > 0:
                            time.sleep(policy.backoff_seconds)

                if last_err is not None and next_state is None:
                    err_detail = _serialize_error(
                        last_err,
                        include_traceback=self.include_tracebacks,
                    )
                    self._emit_payload("step_error", {"state": state, "error": err_detail})
                    self._emit_payload("run_failed", {"error": err_detail, "state": state})
                    raise RunFailed(str(last_err)) from last_err

                if self._after_step is not None:
                    self._after_step(ctx, state, next_state)

                self._emit_payload(
                    "state_exited",
                    {"state": state, "next_state": next_state},
                )
                if next_state is not None and next_state != state:
                    self._emit_payload(
                        "transition",
                        {"from_state": state, "to_state": next_state, "reason": ""},
                    )

                state = next_state if next_state not in ("", None) else None

            self._emit_payload(
                "run_completed",
                {"final_state": self._current_state, "status": "completed"},
            )
            return RunResult(self.run_id, "completed", final_state=self._current_state)
        except RunFailed as e:
            self._emit_payload("run_completed", {"final_state": self._current_state, "status": "failed"})
            return RunResult(self.run_id, "failed", final_state=self._current_state, error=str(e))
        except Exception as e:  # noqa: BLE001
            err_detail = _serialize_error(e, include_traceback=self.include_tracebacks)
            if self._current_state is not None:
                self._emit_payload("step_error", {"state": self._current_state, "error": err_detail})
            self._emit_payload("run_failed", {"error": err_detail, "state": self._current_state})
            self._emit_payload("run_completed", {"final_state": self._current_state, "status": "failed"})
            return RunResult(self.run_id, "failed", final_state=self._current_state, error=str(e))


def resolve_approval_on_store(
    store: EventStore,
    run_id: str,
    approval_id: str,
    *,
    approved: bool,
    resolver: str = "cli",
    reason: str | None = None,
    actor: dict[str, Any] | None = None,
    required_actor_keys: list[str] | tuple[str, ...] | None = None,
    require_reason: bool = False,
    policy_hook: dict[str, Any] | None = None,
) -> None:
    """Append an `approval_resolved` event; resume execution via `Runner.run(..., resume=True)`."""
    events = store.load_events(run_id)
    if not events:
        raise RuntimeError(f"No events found for run_id={run_id!r}")

    want = str(approval_id)
    pending: deque[dict[str, Any]] = deque()
    for event in events:
        payload = event.get("payload") or {}
        aid = payload.get("approval_id")
        aid_str = str(aid) if aid is not None else ""
        if event.get("type") == "approval_requested" and aid_str == want:
            pending.append(payload)
        elif event.get("type") == "approval_resolved" and aid_str == want:
            if pending:
                pending.popleft()

    if not pending:
        raise RuntimeError(f"No pending approval {approval_id!r} found for run_id={run_id!r}")

    missing = missing_actor_fields(actor, required_fields=required_actor_keys)
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"approval actor is missing required keys: {joined}")
    if approval_reason_missing(reason, required=require_reason):
        raise ValueError("approval reason is required")

    payload: dict[str, Any] = {
        "approval_id": str(approval_id),
        "approved": approved,
        "resolver": resolver,
    }
    if reason is not None:
        payload["reason"] = reason
    if actor:
        payload["actor"] = dict(actor)
    if policy_hook:
        payload["policy_hook"] = copy.deepcopy(policy_hook)

    event: dict[str, Any] = {
        "ts": _utcnow_iso(),
        "run_id": run_id,
        "type": "approval_resolved",
        "payload": payload,
    }
    store.append_event(run_id, ts=event["ts"], typ=event["type"], payload=event["payload"])
