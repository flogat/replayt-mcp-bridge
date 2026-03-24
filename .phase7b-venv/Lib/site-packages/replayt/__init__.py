import re

from replayt.exceptions import (
    ApprovalPending,
    ContextSchemaError,
    LogLockError,
    ReplaytError,
    RunFailed,
)
from replayt.notebook import display_graph, display_run
from replayt.runner import RunContext, Runner, RunResult, resolve_approval_on_store
from replayt.testing import MockLLMClient, assert_events, run_with_mock
from replayt.types import LogMode, RetryPolicy
from replayt.workflow import Workflow

_VERSION_PREFIX_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


def _version_tuple_from_string(version: str) -> tuple[int, int, int]:
    match = _VERSION_PREFIX_RE.match(version.strip())
    if not match:
        msg = f"replayt __version__ must begin with major.minor.patch (got {version!r})"
        raise ValueError(msg)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


__all__ = [
    "ApprovalPending",
    "ContextSchemaError",
    "LogLockError",
    "LogMode",
    "MockLLMClient",
    "ReplaytError",
    "RunContext",
    "RunFailed",
    "RunResult",
    "Runner",
    "RetryPolicy",
    "Workflow",
    "__version_tuple__",
    "assert_events",
    "display_graph",
    "display_run",
    "resolve_approval_on_store",
    "run_with_mock",
]

__version__ = "0.4.25"
__version_tuple__: tuple[int, int, int] = _version_tuple_from_string(__version__)
