from __future__ import annotations


class ReplaytError(Exception):
    """Base error for replayt."""


class ApprovalPending(ReplaytError):
    """Raised when a step needs human approval; run is persisted in paused state."""

    def __init__(
        self,
        approval_id: str,
        *,
        summary: str,
        details: dict | None = None,
        on_approve: str | None = None,
        on_reject: str | None = None,
    ) -> None:
        self.approval_id = approval_id
        self.summary = summary
        self.details = details or {}
        self.on_approve = on_approve
        self.on_reject = on_reject
        super().__init__(summary)


class ContextSchemaError(ReplaytError):
    """Raised when step context expectations are not met."""

    def __init__(self, step_name: str, violations: list[str]) -> None:
        self.step_name = step_name
        self.violations = violations
        msg = f"Context schema violation in step {step_name!r}: {'; '.join(violations)}"
        super().__init__(msg)


class RunFailed(ReplaytError):
    """Fatal workflow failure after retries exhausted."""


class LogLockError(ReplaytError):
    """Could not acquire the JSONL file lock (contention or unsupported filesystem)."""
