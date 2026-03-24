from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from replayt.persistence.base import EventStore

_log = logging.getLogger("replayt.persistence")

MirrorErrorHandler = Callable[[str, EventStore, Exception], None]


class MultiStore:
    """Write-through to multiple stores; reads come from the first store.

    **Consistency:** Events are always appended to the *primary* first, then to each
    mirror via ``append``. If a mirror fails and ``strict_mirror`` is false, the primary
    log still contains the event but the mirror may be missing rows; queries against SQLite
    (or a second JSONL file) can then diverge until repaired. Use ``strict_mirror=True``
    when the mirror must stay byte-for-byte consistent with the primary or the run should
    fail. The CLI defaults to strict mirroring whenever ``--sqlite`` is used unless
    ``strict_mirror`` is set false in project config (see ``replayt.cli.config.resolve_strict_mirror``).

    Mirror failures are logged at WARNING. Pass *on_mirror_error* for a callback
    ``(operation, store, exception)`` for alerting or metrics.

    With ``strict_mirror=True``, any mirror write failure is re-raised after logging
    so the run fails loudly. It does **not** provide cross-store atomicity: the primary
    may already contain the event that the mirror missed.
    """

    def __init__(
        self,
        primary: EventStore,
        *mirror: EventStore,
        on_mirror_error: MirrorErrorHandler | None = None,
        strict_mirror: bool = False,
    ) -> None:
        self._primary = primary
        self._mirror = mirror
        self._all = (primary, *mirror)
        self._on_mirror_error = on_mirror_error
        self._strict_mirror = strict_mirror
        self.mirror_error_count: int = 0

    def close(self) -> None:
        """Close any store that exposes ``close`` (primary first, then mirrors).

        The JSONL primary usually has no ``close``; SQLite mirrors (and any DB-backed primary)
        still release handles without leaking connections across composite layouts.
        """

        for store in self._all:
            closer = getattr(store, "close", None)
            if callable(closer):
                closer()

    def _handle_mirror_error(self, operation: str, store: EventStore, exc: Exception, run_id: str) -> None:
        self.mirror_error_count += 1
        _log.warning("Mirror store %s failed for run_id=%s", operation, run_id, exc_info=True)
        if self._on_mirror_error is not None:
            self._on_mirror_error(operation, store, exc)
        if self._strict_mirror:
            raise exc

    def append_event(self, run_id: str, *, ts: str, typ: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = self._primary.append_event(run_id, ts=ts, typ=typ, payload=payload)
        for store in self._mirror:
            try:
                store.append(run_id, event)
            except Exception as exc:  # noqa: BLE001
                self._handle_mirror_error("append_event", store, exc, run_id)
        return event

    def append(self, run_id: str, event: dict[str, Any]) -> None:
        self._primary.append(run_id, event)
        for store in self._mirror:
            try:
                store.append(run_id, event)
            except Exception as exc:  # noqa: BLE001
                self._handle_mirror_error("append", store, exc, run_id)

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        return self._primary.load_events(run_id)

    def list_run_ids(self) -> list[str]:
        return self._primary.list_run_ids()

    def delete_run(self, run_id: str) -> int:
        result = self._primary.delete_run(run_id)
        for store in self._mirror:
            try:
                store.delete_run(run_id)
            except Exception as exc:  # noqa: BLE001
                self._handle_mirror_error("delete_run", store, exc, run_id)
        return result
