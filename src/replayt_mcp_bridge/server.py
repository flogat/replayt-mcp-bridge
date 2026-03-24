"""Minimal MCP server (stdio) for replayt-mcp-bridge."""

from __future__ import annotations

import contextvars
import functools
import logging
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

import typer
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context
from mcp.server.fastmcp.utilities.context_injection import find_context_parameter

from replayt.cli.config import DEFAULT_LOG_DIR, resolve_log_dir
from replayt.cli.targets import load_target
from replayt.cli.validation import validate_workflow_graph, validation_report
from replayt.graph_export import workflow_to_mermaid
from replayt.persistence import SQLiteStore
from replayt.persistence.jsonl import (
    JSONLStore,
    validate_run_id as validate_run_id_for_store,
)

from replayt_mcp_bridge import (
    installed_replayt_version,
    installed_replayt_version_tuple,
)
from replayt_mcp_bridge.observability import (
    configure_bridge_logging,
    emit_json_log,
    parse_store_hint_allowlist_roots,
    redact_structure,
    run_events_redaction_enabled,
)

mcp = FastMCP("replayt-mcp-bridge")
logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., dict[str, Any]])

_tool_invocation_correlation_id: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar(
        "replayt_mcp_bridge_tool_invocation_correlation_id", default=None
    )
)


def _correlation_id_for_invocation(ctx: Any) -> str:
    """Prefer FastMCP ``Context.request_id`` when non-empty; else a new UUID4 (per MCP_TOOLS)."""

    if ctx is not None:
        try:
            rid = str(ctx.request_id).strip()
            if rid:
                return rid
        except (ValueError, AttributeError):
            pass
    return str(uuid.uuid4())


def _active_tool_correlation_id() -> str:
    """Correlation id for the current tool handler (set by ``_log_replayt_tool_boundaries``)."""

    cid = _tool_invocation_correlation_id.get()
    if cid is None:
        raise RuntimeError("replayt_mcp_bridge internal: tool correlation_id not set")
    return cid


def _log_replayt_tool_boundaries(fn: F) -> F:
    """Log tool name, correlation id, optional MCP request id, and outcome status."""

    name = fn.__name__
    ctx_kw = find_context_parameter(fn)

    @functools.wraps(fn)
    def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any]:
        ctx = kwargs.get(ctx_kw) if ctx_kw else None
        correlation_id = _correlation_id_for_invocation(ctx)
        reset_token = _tool_invocation_correlation_id.set(correlation_id)
        corr: dict[str, Any] = {"correlation_id": correlation_id}
        if ctx is not None:
            try:
                corr["mcp_request_id"] = ctx.request_id
            except ValueError:
                pass
        try:
            emit_json_log(
                logger, logging.INFO, "replayt_mcp_bridge.tool.begin", tool=name, **corr
            )
            try:
                out = fn(*args, **kwargs)
            except Exception:
                emit_json_log(
                    logger,
                    logging.ERROR,
                    "replayt_mcp_bridge.tool.unhandled_exception",
                    tool=name,
                    **corr,
                )
                logger.exception("replayt_mcp_bridge.tool.unhandled_exception_trace")
                raise
            status = out.get("status") if isinstance(out, dict) else None
            emit_json_log(
                logger,
                logging.INFO,
                "replayt_mcp_bridge.tool.end",
                tool=name,
                status=status,
                **corr,
            )
            return out
        finally:
            _tool_invocation_correlation_id.reset(reset_token)

    return wrapped  # type: ignore[return-value]


def _tool_error(*, tool: str, replayt_surface: str, message: str) -> dict[str, Any]:
    cid = _tool_invocation_correlation_id.get()
    out: dict[str, Any] = {
        "status": "error",
        "tool": tool,
        "replayt_surface": replayt_surface,
        "message": message,
    }
    if cid is not None:
        out["correlation_id"] = cid
    return out


def _path_allowed_under_store_hint_roots(path: Path, roots: list[Path]) -> bool:
    return any(path.is_relative_to(root) for root in roots)


def _split_typed_store_hint(store_hint: str) -> tuple[str | None, str]:
    """If ``store_hint`` uses an explicit kind prefix, return ``(kind, path_str)`` else ``(None, original)``.

    Recognized prefixes (ASCII, case-insensitive): ``jsonl:``, ``sqlite:``. The remainder is trimmed of leading
    whitespace and passed through ``expanduser`` / ``resolve`` like legacy hints. Any other string is treated as a
    legacy opaque filesystem path (backward compatible).
    """

    s = store_hint.strip()
    lower = s.lower()
    if lower.startswith("jsonl:"):
        return "jsonl", s[6:].lstrip()
    if lower.startswith("sqlite:"):
        return "sqlite", s[7:].lstrip()
    return None, s


def _resolve_persistence_paths(
    store_hint: str | None,
) -> tuple[Path | None, Path | None, str | None]:
    """Return ``(log_dir, sqlite_path, error)`` for JSONL (directory) or SQLite file backends."""

    if store_hint is None:
        return resolve_log_dir(DEFAULT_LOG_DIR), None, None
    explicit_kind, path_str = _split_typed_store_hint(store_hint)
    if explicit_kind is not None and not path_str:
        return (
            None,
            None,
            "store_hint uses a typed prefix (jsonl: or sqlite:) but the path part is empty; "
            "see docs/MCP_TOOLS.md (store_hint grammar).",
        )
    raw = Path(path_str).expanduser()
    try:
        p = raw.resolve(strict=False)
    except (OSError, RuntimeError):
        p = raw
    if explicit_kind == "sqlite":
        return None, p, None
    if explicit_kind == "jsonl":
        if p.exists() and p.is_file():
            return (
                None,
                None,
                "jsonl: store_hint must refer to a JSONL log directory, not a file.",
            )
        return p, None, None

    suf = p.suffix.lower()
    if suf in (".sqlite", ".db"):
        return None, p, None
    if p.exists() and p.is_file():
        return (
            None,
            None,
            f"Store hint {store_hint!r} is a plain file; pass a JSONL log directory or a .sqlite/.db path.",
        )
    return p, None, None


@contextmanager
def _open_read_store(
    log_dir: Path | None, sqlite: Path | None
) -> Iterator[JSONLStore | SQLiteStore]:
    if sqlite is not None:
        st = SQLiteStore(sqlite, read_only=True)
        try:
            yield st
        finally:
            st.close()
    else:
        assert log_dir is not None
        yield JSONLStore(log_dir, create=False)


@mcp.tool()
@_log_replayt_tool_boundaries
def replayt_echo(message: str, ctx: Context | None = None) -> dict[str, Any]:
    """Echo a string back to the client to verify MCP tool invocation and stdio wiring."""

    return {"status": "ok", "echo": message}


@mcp.tool()
@_log_replayt_tool_boundaries
def replayt_version_info(ctx: Context | None = None) -> dict[str, Any]:
    """Report installed replayt and bridge versions (PEP 440 string and replayt's version tuple)."""

    major, minor, patch = installed_replayt_version_tuple()
    return {
        "status": "ok",
        "replayt_version": installed_replayt_version(),
        "replayt_version_tuple": {"major": major, "minor": minor, "patch": patch},
        "bridge_package": "replayt-mcp-bridge",
    }


@mcp.tool()
@_log_replayt_tool_boundaries
def workflow_contract_snapshot(
    target: str, ctx: Context | None = None
) -> dict[str, Any]:
    """Return a JSON-serializable workflow contract snapshot for a replayt target (MODULE:VAR or workflow file).

    Maps to replayt.workflow.Workflow.contract() after resolving the target the same way as the replayt CLI.
    """

    tool = "workflow_contract_snapshot"
    surface = "Workflow.contract + replayt.cli.targets.load_target"
    try:
        wf = load_target(target)
        contract = wf.contract()
    except typer.BadParameter as exc:
        return _tool_error(tool=tool, replayt_surface=surface, message=str(exc))
    return {"status": "ok", "target": target, "contract": contract}


@mcp.tool()
@_log_replayt_tool_boundaries
def workflow_graph_mermaid(target: str, ctx: Context | None = None) -> dict[str, Any]:
    """Return Mermaid text for a workflow graph (same intent as `replayt graph`)."""

    tool = "workflow_graph_mermaid"
    surface = "replayt.graph_export.workflow_to_mermaid"
    try:
        wf = load_target(target)
        mermaid = workflow_to_mermaid(wf)
    except typer.BadParameter as exc:
        return _tool_error(tool=tool, replayt_surface=surface, message=str(exc))
    return {"status": "ok", "target": target, "mermaid": mermaid}


@mcp.tool()
@_log_replayt_tool_boundaries
def runner_dry_run_plan(
    target: str,
    inputs_json: str | None = None,
    strict_graph: bool = False,
    metadata_json: str | None = None,
    experiment_json: str | None = None,
    policy_hook_context_json: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Plan or validate a run without committing side effects (aligned with `replayt run --dry-check` semantics)."""

    tool = "runner_dry_run_plan"
    surface = "replayt run --dry-check / validate_workflow_graph + validation_report"
    try:
        wf = load_target(target)
        errors, warnings = validate_workflow_graph(wf, strict_graph=strict_graph)
        report = validation_report(
            target=target,
            wf=wf,
            strict_graph=strict_graph,
            errors=errors,
            warnings=warnings,
            inputs_json=inputs_json,
            metadata_json=metadata_json,
            experiment_json=experiment_json,
            policy_hook_context_json=policy_hook_context_json,
        )
    except typer.BadParameter as exc:
        return _tool_error(tool=tool, replayt_surface=surface, message=str(exc))
    status = "ok" if report["ok"] else "invalid"
    return {"status": status, "report": report}


@mcp.tool()
@_log_replayt_tool_boundaries
def persistence_list_run_events(
    run_id: str, store_hint: str | None = None, ctx: Context | None = None
) -> dict[str, Any]:
    """List persisted events for a run_id (aligned with EventStore.load_events and `replayt runs` tooling)."""

    tool = "persistence_list_run_events"
    surface = "EventStore.load_events (JSONL directory or SQLite file)"
    try:
        safe_run_id = validate_run_id_for_store(run_id)
    except ValueError as exc:
        return _tool_error(tool=tool, replayt_surface=surface, message=str(exc))
    log_dir, sqlite, hint_err = _resolve_persistence_paths(store_hint)
    if hint_err:
        return _tool_error(tool=tool, replayt_surface=surface, message=hint_err)
    allow_roots = parse_store_hint_allowlist_roots()
    if store_hint is not None and allow_roots is not None:
        if not allow_roots:
            emit_json_log(
                logger,
                logging.WARNING,
                "replayt_mcp_bridge.store_hint.rejected",
                reason="allowlist_unusable",
                correlation_id=_active_tool_correlation_id(),
            )
            return _tool_error(
                tool=tool,
                replayt_surface=surface,
                message=(
                    "REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS is set but no valid absolute "
                    "roots were parsed; refusing explicit store_hint."
                ),
            )
        store_path = sqlite if sqlite is not None else log_dir
        assert store_path is not None
        if not _path_allowed_under_store_hint_roots(store_path, allow_roots):
            emit_json_log(
                logger,
                logging.WARNING,
                "replayt_mcp_bridge.store_hint.rejected",
                reason="outside_allowlist",
                correlation_id=_active_tool_correlation_id(),
            )
            return _tool_error(
                tool=tool,
                replayt_surface=surface,
                message=(
                    "Store hint resolves outside REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS; "
                    "see docs/SECURITY.md."
                ),
            )
    if sqlite is not None and not sqlite.is_file():
        return _tool_error(
            tool=tool,
            replayt_surface=surface,
            message=f"SQLite store not found: {sqlite}",
        )
    try:
        with _open_read_store(log_dir, sqlite) as store:
            events = store.load_events(safe_run_id)
    except OSError as exc:
        return _tool_error(tool=tool, replayt_surface=surface, message=str(exc))
    if run_events_redaction_enabled():
        events_for_client: Any = redact_structure(events)
    else:
        events_for_client = events
    store_kind = "sqlite" if sqlite is not None else "jsonl"
    store_path = str(sqlite) if sqlite is not None else str(log_dir)
    return {
        "status": "ok",
        "run_id": safe_run_id,
        "event_count": len(events),
        "events": events_for_client,
        "store": {"kind": store_kind, "path": store_path},
    }


def run_stdio() -> None:
    """Run the MCP server on stdin/stdout (JSON-RPC per MCP)."""

    configure_bridge_logging()
    emit_json_log(
        logger, logging.INFO, "replayt_mcp_bridge.server.start", transport="stdio"
    )
    mcp.run(transport="stdio")
