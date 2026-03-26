from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any, TypeVar

from replayt.types import RetryPolicy

F = TypeVar("F", bound=Callable[..., Any])
_WORKFLOW_CONTRACT_SCHEMA = "replayt.workflow_contract.v1"


class Workflow:
    """Finite-state workflow definition with explicit handlers and optional metadata."""

    def __init__(
        self,
        name: str,
        *,
        version: str = "1",
        meta: dict[str, Any] | None = None,
        llm_defaults: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.version = version
        #: Optional JSON-serializable bag (package id, git SHA, etc.) emitted on ``run_started`` as ``workflow_meta``.
        self.meta = dict(meta) if meta else None
        #: Merged into :class:`~replayt.llm.LLMBridge` defaults (logged as ``effective`` on each LLM call).
        self.llm_defaults = dict(llm_defaults) if llm_defaults else None
        self.initial_state: str | None = None
        self._steps: dict[str, Callable[..., Any]] = {}
        self._retries: dict[str, RetryPolicy] = {}
        self._edges: list[tuple[str, str]] = []
        self._expects: dict[str, dict[str, type]] = {}

    def set_initial(self, state: str) -> None:
        self.initial_state = state

    def step(
        self, name: str, *, retries: RetryPolicy | None = None, expects: dict[str, type] | list[str] | None = None
    ) -> Callable[[F], F]:
        def deco(fn: F) -> F:
            self._steps[name] = fn
            if retries is not None:
                self._retries[name] = retries
            if expects is not None:
                if isinstance(expects, list):
                    self._expects[name] = {key: object for key in expects}
                else:
                    self._expects[name] = expects
            return fn

        return deco

    def get_handler(self, name: str) -> Callable[..., Any]:
        if name not in self._steps:
            raise KeyError(f"Unknown step/state: {name}")
        return self._steps[name]

    def expects_for(self, name: str) -> dict[str, type]:
        return self._expects.get(name, {})

    def retry_policy_for(self, name: str) -> RetryPolicy:
        return self._retries.get(name, RetryPolicy())

    def step_names(self) -> list[str]:
        return sorted(self._steps.keys())

    def note_transition(self, from_state: str, to_state: str) -> None:
        """Optional documentation edge for `replayt graph` or validation."""

        edge = (from_state, to_state)
        if edge not in self._edges:
            self._edges.append(edge)

    def edges(self) -> list[tuple[str, str]]:
        return list(self._edges)

    def allows_transition(self, from_state: str, to_state: str | None) -> bool:
        if to_state in (None, ""):
            return True
        if not self._edges:
            return True
        return (from_state, to_state) in self._edges

    @staticmethod
    def _type_label(tp: type) -> str:
        if tp is object:
            return "any"
        return getattr(tp, "__name__", repr(tp))

    @staticmethod
    def _contract_sha256(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _contract_payload(self) -> dict[str, Any]:
        edges_by_source: dict[str, list[str]] = {}
        for src, dst in self._edges:
            edges_by_source.setdefault(src, []).append(dst)
        llm_defaults_keys: set[str] = set((self.llm_defaults or {}).keys())
        meta_llm_defaults = (self.meta or {}).get("llm_defaults")
        if isinstance(meta_llm_defaults, dict):
            llm_defaults_keys.update(meta_llm_defaults.keys())

        steps: list[dict[str, Any]] = []
        for name in self.step_names():
            expects = [
                {"key": key, "type": self._type_label(expected_type)}
                for key, expected_type in sorted(self.expects_for(name).items())
            ]
            retry = self.retry_policy_for(name)
            steps.append(
                {
                    "name": name,
                    "expects": expects,
                    "retry_policy": {
                        "max_attempts": retry.max_attempts,
                        "backoff_seconds": retry.backoff_seconds,
                    },
                    "outgoing_transitions": list(edges_by_source.get(name, [])),
                }
            )

        visible_meta = dict(self.meta or {})
        visible_meta.pop("llm_defaults", None)
        return {
            "schema": _WORKFLOW_CONTRACT_SCHEMA,
            "workflow": {
                "name": self.name,
                "version": self.version,
                "initial_state": self.initial_state,
                "state_count": len(steps),
                "edge_count": len(self._edges),
                "meta_keys": sorted(visible_meta.keys()),
                "llm_defaults_keys": sorted(llm_defaults_keys),
            },
            "declared_edges": [{"from_state": src, "to_state": dst} for src, dst in self._edges],
            "steps": steps,
        }

    def contract_digest(self) -> str:
        """Return a stable digest for the workflow surface used by `Workflow.contract()`."""

        return self._contract_sha256(self._contract_payload())

    def contract(self) -> dict[str, Any]:
        """Return a stable, snapshot-friendly description of the workflow surface."""

        payload = self._contract_payload()
        payload["contract_sha256"] = self._contract_sha256(payload)
        return payload
