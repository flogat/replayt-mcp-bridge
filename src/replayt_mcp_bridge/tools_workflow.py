"""MCP tools: workflow introspection and dry-run planning."""

from __future__ import annotations

from typing import Any

import typer
from mcp.server.fastmcp import Context
from replayt.cli.targets import load_target
from replayt.cli.validation import validate_workflow_graph, validation_report
from replayt.graph_export import workflow_to_mermaid

from replayt_mcp_bridge.mcp_instance import mcp
from replayt_mcp_bridge.utils import _correlation_id_for_invocation, _tool_error, with_timeout
from replayt_mcp_bridge.tools_common import _log_replayt_tool_boundaries


@mcp.tool()
@_log_replayt_tool_boundaries
async def workflow_contract_snapshot(
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
async def workflow_graph_mermaid(target: str, ctx: Context | None = None) -> dict[str, Any]:
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
async def runner_dry_run_plan(
    target: str,
    inputs_json: str | None = None,
    strict_graph: bool = False,
    metadata_json: str | None = None,
    experiment_json: str | None = None,
    policy_hook_context_json: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Plan or validate a run without committing side effects (aligned with `replayt run --dry-check` semantics)."""

    # Wrap the actual implementation with a timeout
    return await with_timeout(
        _runner_dry_run_plan_impl,
        "runner_dry_run_plan",
    )(
        target,
        inputs_json,
        strict_graph,
        metadata_json,
        experiment_json,
        policy_hook_context_json,
        ctx,
    )


async def _runner_dry_run_plan_impl(
    target: str,
    inputs_json: str | None,
    strict_graph: bool,
    metadata_json: str | None,
    experiment_json: str | None,
    policy_hook_context_json: str | None,
    ctx: Context | None,
) -> dict[str, Any]:
    """Implementation of runner_dry_run_plan (wrapped with timeout)."""
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
