from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LogMode(str, Enum):
    """How much LLM traffic to persist.

    ``structured_only``: log ``llm_request`` / ``llm_response`` with only state, timing, usage, and
    effective settings (no message bodies, role lists, or content previews). Pair with
    :meth:`replayt.llm.LLMBridge.parse` for ``structured_output`` events without raw model text in the log;
    successful parses also copy ``usage``, ``latency_ms``, ``finish_reason``, and the resolved ``effective``
    settings onto ``structured_output`` so cost, latency, and model settings stay on that event alone.
    """

    redacted = "redacted"
    full = "full"
    structured_only = "structured_only"


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    backoff_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1, got {self.max_attempts}")
