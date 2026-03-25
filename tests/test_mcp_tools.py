from __future__ import annotations

import json
from pathlib import Path

import pytest

from replayt_mcp_bridge.persistence_support import _split_typed_store_hint
from replayt_mcp_bridge.tools_health import replayt_echo, replayt_version_info
from replayt_mcp_bridge.tools_persistence import persistence_list_run_events
from replayt_mcp_bridge.tools_workflow import (
    runner_dry_run_plan,
    workflow_contract_snapshot,
    workflow_graph_mermaid,
)
from replayt_mcp_bridge.tools_persistence import SQLiteStore


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
    # Use a valid target string (e.g., a module path or a workflow file path)
    # For this test, we'll use a dummy target that should fail gracefully
    # or a known valid target if available in the test environment.
    # Since we don't have a guaranteed valid target, we'll test the error path.
    out = workflow_contract_snapshot("invalid_target_xyz")
    assert out["status"] == "error"
    assert out["tool"] == "workflow_contract_snapshot"


def test_workflow_graph_mermaid() -> None:
    # Test error path with invalid target
    out = workflow_graph_mermaid("invalid_target_xyz")
    assert out["status"] == "error"
    assert out["tool"] == "workflow_graph_mermaid"


def test_runner_dry_run_plan() -> None:
    # Test error path with invalid target
    out = runner_dry_run_plan("invalid_target_xyz")
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
    out = persistence_list_run_events(run_id=run_id, store_hint=str(db))
    assert out["status"] == "ok"
    assert out["store"]["kind"] == "sqlite"


def test_tool_timeout_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that a tool exceeding the timeout returns a structured error."""
    import asyncio
    from replayt_mcp_bridge.server import with_timeout

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
