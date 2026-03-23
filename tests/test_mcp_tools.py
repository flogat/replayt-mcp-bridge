"""Contract tests for the initial MCP tool surface (see docs/MCP_TOOLS.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from replayt_mcp_bridge import installed_replayt_version
from replayt_mcp_bridge.server import (
    persistence_list_run_events,
    replayt_echo,
    replayt_version_info,
    runner_dry_run_plan,
    workflow_contract_snapshot,
    workflow_graph_mermaid,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_TOOLS_DOC = REPO_ROOT / "docs" / "MCP_TOOLS.md"


def test_mcp_tools_doc_exists_and_has_mapping_table() -> None:
    text = MCP_TOOLS_DOC.read_text(encoding="utf-8")
    assert "## Mapping: tool → replayt capability" in text
    for name in (
        "replayt_echo",
        "replayt_version_info",
        "workflow_contract_snapshot",
        "workflow_graph_mermaid",
        "runner_dry_run_plan",
        "persistence_list_run_events",
    ):
        assert name in text


def test_replayt_echo_returns_payload() -> None:
    assert replayt_echo(message="hello") == {"status": "ok", "echo": "hello"}


def test_replayt_version_info_matches_installed_replayt() -> None:
    info = replayt_version_info()
    assert info["status"] == "ok"
    assert info["replayt_version"] == installed_replayt_version()
    tup = info["replayt_version_tuple"]
    assert tuple(sorted(tup)) == ("major", "minor", "patch")
    assert isinstance(tup["major"], int)


@pytest.mark.parametrize(
    ("fn", "kwargs"),
    [
        (workflow_contract_snapshot, {"target": "example.module:wf"}),
        (workflow_graph_mermaid, {"target": "workflow.py"}),
        (runner_dry_run_plan, {"target": "m:wf", "inputs_json": None}),
        (persistence_list_run_events, {"run_id": "00000000-0000-0000-0000-000000000000", "store_hint": None}),
    ],
)
def test_stub_tools_return_not_implemented(fn, kwargs: dict) -> None:
    out = fn(**kwargs)
    assert out["status"] == "not_implemented"
    assert out["tool"] == fn.__name__
    assert "replayt_surface" in out
