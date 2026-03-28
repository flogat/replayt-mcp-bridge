from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from replayt.persistence import SQLiteStore

from replayt_mcp_bridge.tools_health import replayt_echo, replayt_version_info
from replayt_mcp_bridge.tools_persistence import persistence_list_run_events
from replayt_mcp_bridge.observability import resolve_bridge_tool_timeout_seconds
from replayt_mcp_bridge.tools_workflow import (
    runner_dry_run_plan,
    workflow_contract_snapshot,
    workflow_graph_mermaid,
)
import replayt_mcp_bridge.tools_workflow as tools_workflow_mod
from replayt_mcp_bridge.utils import with_timeout


def test_replayt_echo() -> None:
    out = replayt_echo("hello")
    assert out["status"] == "ok"
    assert out["echo"] == "hello"


def test_replayt_version_info() -> None:
    out = replayt_version_info()
    assert out["status"] == "ok"
    assert "replayt_version" in out
    assert isinstance(out["replayt_version"], str)


def test_workflow_contract_snapshot() -> None:
    out = asyncio.run(workflow_contract_snapshot("invalid_target_xyz"))
    assert out["status"] == "error"
    assert out["tool"] == "workflow_contract_snapshot"


def test_workflow_graph_mermaid() -> None:
    out = asyncio.run(workflow_graph_mermaid("invalid_target_xyz"))
    assert out["status"] == "error"
    assert out["tool"] == "workflow_graph_mermaid"


def test_runner_dry_run_plan() -> None:
    out = asyncio.run(runner_dry_run_plan("invalid_target_xyz"))
    assert out["status"] == "error"
    assert out["tool"] == "runner_dry_run_plan"


def test_persistence_list_run_events_allowlist_sqlite_under_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "r"
    root.mkdir()
    monkeypatch.setenv("REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS", str(root))
    db = root / "e.sqlite"
    run_id = "sql-allow"
    st = SQLiteStore(db, read_only=False)
    try:
        st.append_event(
            run_id,
            ts="2020-01-01T00:00:00Z",
            typ="unit_test_marker",
            payload={},
        )
    finally:
        st.close()
    out = asyncio.run(persistence_list_run_events(run_id=run_id, store_hint=str(db)))
    assert out["status"] == "ok"
    assert out["store"]["kind"] == "sqlite"


def test_tool_timeout_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that a tool exceeding the timeout returns a structured error."""
    monkeypatch.setenv("REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_SECONDS", "0.1")

    # Mock a slow handler that sleeps longer than the timeout
    async def slow_handler():
        await asyncio.sleep(1.0)
        return {"status": "ok"}

    # Wrap the slow handler with the real timeout wrapper
    wrapped = with_timeout(slow_handler, "test_tool")
    # Run it and expect a timeout error
    result = asyncio.run(wrapped())
    assert result["status"] == "error"
    assert result["replayt_surface"] == "bridge_timeout"
    assert result["tool"] == "test_tool"
    assert "correlation_id" in result
    assert result["timeout_seconds"] == 0.1
    assert result["timeout_source"] == "global_env"
    assert "traceback" not in result


def test_resolve_bridge_tool_timeout_defaults_to_300(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv(
        "REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_RUNNER_DRY_RUN_PLAN_SECONDS",
        raising=False,
    )
    lim, src = resolve_bridge_tool_timeout_seconds("runner_dry_run_plan")
    assert lim == 300.0
    assert src == "default"


def test_resolve_bridge_tool_timeout_per_tool_overrides_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_SECONDS", "99")
    monkeypatch.setenv(
        "REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_RUNNER_DRY_RUN_PLAN_SECONDS",
        "12",
    )
    lim, src = resolve_bridge_tool_timeout_seconds("runner_dry_run_plan")
    assert lim == 12.0
    assert src == "per_tool_env"


def test_resolve_bridge_tool_timeout_invalid_global_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_SECONDS", "not-a-float")
    monkeypatch.delenv(
        "REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_RUNNER_DRY_RUN_PLAN_SECONDS",
        raising=False,
    )
    lim, src = resolve_bridge_tool_timeout_seconds("runner_dry_run_plan")
    assert lim == 300.0
    assert src == "default"


def test_resolve_bridge_tool_timeout_global_zero_disables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_RUNNER_DRY_RUN_PLAN_SECONDS",
        raising=False,
    )
    monkeypatch.setenv("REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_SECONDS", "0")
    lim, src = resolve_bridge_tool_timeout_seconds("runner_dry_run_plan")
    assert lim is None
    assert src == "global_env"


def test_workflow_contract_snapshot_timeout_registered_tool_cooperative_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registered tool: short limit + ``await asyncio.sleep`` before real impl (cooperative; sync sleep would starve the loop)."""
    real_impl = tools_workflow_mod._workflow_contract_snapshot_impl

    async def impl_with_cooperative_delay(target: str, ctx):
        await asyncio.sleep(1.0)
        return await real_impl(target, ctx)

    monkeypatch.setenv("REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_SECONDS", "0.15")
    monkeypatch.setattr(
        tools_workflow_mod,
        "_workflow_contract_snapshot_impl",
        impl_with_cooperative_delay,
    )

    out = asyncio.run(workflow_contract_snapshot("invalid_target_xyz"))
    assert out["status"] == "error"
    assert out["replayt_surface"] == "bridge_timeout"
    assert out["tool"] == "workflow_contract_snapshot"
    assert "correlation_id" in out
    assert out["timeout_source"] == "global_env"
    assert out["timeout_seconds"] == 0.15
    assert "traceback" not in out
