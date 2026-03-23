"""Minimal MCP server (stdio) for replayt-mcp-bridge."""

from __future__ import annotations

import functools
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

import typer
from mcp.server.fastmcp import FastMCP

from replayt.cli.config import DEFAULT_LOG_DIR, resolve_log_dir
from replayt.cli.targets import load_target
from replayt.cli.validation import validate_workflow_graph, validation_report
from replayt.graph_export import workflow_to_mermaid
from replayt.persistence import SQLiteStore
from replayt.persistence.jsonl import JSONLStore, validate_run_id as validate_run_id_for_store

from replayt_mcp_bridge import installed_replayt_version, installed_replayt_version_tuple

mcp = FastMCP("replayt-mcp-bridge")
logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., dict[str, Any]])


def _log_replayt_tool_boundaries(fn: F) -> F:
    """Log tool name and outcome status only (no client argument values)."""

    name = fn.__name__

    @functools.wraps(fn)
    def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any]:
        logger.info("replayt_mcp_bridge.tool.begin", extra={"tool": name})
        try:
            out = fn(*args, **kwargs)
        except Exception:
            logger.exception("replayt_mcp_bridge.tool.unhandled_exception", extra={"tool": name})
            raise
        status = out.get("status") if isinstance(out, dict) else None
        logger.info("replayt_mcp_bridge.tool.end", extra={"tool": name, "status": status})
        return out

    return wrapped  # type: ignore[return-value]


def _tool_error(*, tool: str, replayt_surface: str, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "tool": tool,
        "replayt_surface": replayt_surface,
        "message": message,
    }


def _resolve_persistence_paths(store_hint: str | None) -> tuple[Path | None, Path | None, str | None]:
    """Return ``(log_dir, sqlite_path, error)`` for JSONL (directory) or SQLite file backends."""

    if store_hint is None:
        return resolve_log_dir(DEFAULT_LOG_DIR), None, None
    raw = Path(store_hint).expanduser()
    try:
        p = raw.resolve(strict=False)
    except (OSError, RuntimeError):
        p = raw
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
def _open_read_store(log_dir: Path | None, sqlite: Path | None) -> Iterator[JSONLStore | SQLiteStore]:
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
def replayt_echo(message: str) -> dict[str, Any]:
    """Echo a string back to the client to verify MCP tool invocation and stdio wiring."""

    return {"status": "ok", "echo": message}


@mcp.tool()
@_log_replayt_tool_boundaries
def replayt_version_info() -> dict[str, Any]:
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
def workflow_contract_snapshot(target: str) -> dict[str, Any]:
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
def workflow_graph_mermaid(target: str) -> dict[str, Any]:
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
def runner_dry_run_plan(target: str, inputs_json: str | None = None) -> dict[str, Any]:
    """Plan or validate a run without committing side effects (aligned with `replayt run --dry-check` semantics)."""

    tool = "runner_dry_run_plan"
    surface = "replayt run --dry-check / validate_workflow_graph + validation_report"
    strict_graph = False
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
            metadata_json=None,
            experiment_json=None,
            policy_hook_context_json=None,
        )
    except typer.BadParameter as exc:
        return _tool_error(tool=tool, replayt_surface=surface, message=str(exc))
    status = "ok" if report["ok"] else "invalid"
    return {"status": status, "report": report}


@mcp.tool()
@_log_replayt_tool_boundaries
def persistence_list_run_events(run_id: str, store_hint: str | None = None) -> dict[str, Any]:
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
    store_kind = "sqlite" if sqlite is not None else "jsonl"
    store_path = str(sqlite) if sqlite is not None else str(log_dir)
    return {
        "status": "ok",
        "run_id": safe_run_id,
        "event_count": len(events),
        "events": events,
        "store": {"kind": store_kind, "path": store_path},
    }


def run_stdio() -> None:
    """Run the MCP server on stdin/stdout (JSON-RPC per MCP)."""

    logger.info("replayt_mcp_bridge.server.start", extra={"transport": "stdio"})
    mcp.run(transport="stdio")
