"""Minimal MCP server (stdio) for replayt-mcp-bridge."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from replayt_mcp_bridge import installed_replayt_version, installed_replayt_version_tuple

mcp = FastMCP("replayt-mcp-bridge")


def _stub(tool: str, surface: str, detail: str = "") -> dict[str, Any]:
    msg = "Implementation scheduled for a later bridge slice; contract is stable for clients."
    if detail:
        msg = f"{detail} {msg}"
    return {
        "status": "not_implemented",
        "tool": tool,
        "replayt_surface": surface,
        "message": msg.strip(),
    }


@mcp.tool()
def replayt_echo(message: str) -> dict[str, Any]:
    """Echo a string back to the client to verify MCP tool invocation and stdio wiring."""

    return {"status": "ok", "echo": message}


@mcp.tool()
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
def workflow_contract_snapshot(target: str) -> dict[str, Any]:
    """Return a JSON-serializable workflow contract snapshot for a replayt target (MODULE:VAR or workflow file).

    Maps to replayt.workflow.Workflow.contract() after resolving the target the same way as the replayt CLI.
    """

    return _stub(
        "workflow_contract_snapshot",
        "Workflow.contract + replayt.cli.targets.load_target",
        f"Requested target={target!r}.",
    )


@mcp.tool()
def workflow_graph_mermaid(target: str) -> dict[str, Any]:
    """Return Mermaid text for a workflow graph (same intent as `replayt graph`)."""

    return _stub(
        "workflow_graph_mermaid",
        "replayt.graph_export.workflow_to_mermaid",
        f"Requested target={target!r}.",
    )


@mcp.tool()
def runner_dry_run_plan(target: str, inputs_json: str | None = None) -> dict[str, Any]:
    """Plan or validate a run without committing side effects (aligned with `replayt run --dry-check` semantics)."""

    return _stub(
        "runner_dry_run_plan",
        "replayt run --dry-check / Runner",
        f"Requested target={target!r} inputs_json={'set' if inputs_json else 'none'}.",
    )


@mcp.tool()
def persistence_list_run_events(run_id: str, store_hint: str | None = None) -> dict[str, Any]:
    """List persisted events for a run_id (aligned with EventStore.load_events and `replayt runs` tooling)."""

    return _stub(
        "persistence_list_run_events",
        "EventStore.load_events",
        f"Requested run_id={run_id!r} store_hint={store_hint!r}.",
    )


def run_stdio() -> None:
    """Run the MCP server on stdin/stdout (JSON-RPC per MCP)."""

    mcp.run(transport="stdio")
