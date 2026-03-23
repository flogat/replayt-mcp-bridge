"""Contract tests for the initial MCP tool surface (see docs/MCP_TOOLS.md)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from replayt.persistence import SQLiteStore

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
EXAMPLE_TARGET = "replayt_examples.e01_hello_world:wf"


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


def test_workflow_contract_snapshot_example_target() -> None:
    out = workflow_contract_snapshot(target=EXAMPLE_TARGET)
    assert out["status"] == "ok"
    assert out["target"] == EXAMPLE_TARGET
    contract = out["contract"]
    assert isinstance(contract, dict)
    assert "contract_sha256" in contract


def test_workflow_contract_snapshot_bad_target() -> None:
    out = workflow_contract_snapshot(target="definitely_not_a_module:wf")
    assert out["status"] == "error"
    assert out["tool"] == "workflow_contract_snapshot"
    assert "message" in out


def test_replayt_version_info_logs_tool_boundaries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="replayt_mcp_bridge.server")
    replayt_version_info()
    msgs = {r.msg for r in caplog.records}
    assert "replayt_mcp_bridge.tool.begin" in msgs
    assert "replayt_mcp_bridge.tool.end" in msgs


def test_workflow_graph_mermaid_example_target() -> None:
    out = workflow_graph_mermaid(target=EXAMPLE_TARGET)
    assert out["status"] == "ok"
    assert out["target"] == EXAMPLE_TARGET
    assert isinstance(out["mermaid"], str)
    assert len(out["mermaid"]) > 0


def test_workflow_graph_mermaid_bad_target() -> None:
    out = workflow_graph_mermaid(target="definitely_not_a_module:wf")
    assert out["status"] == "error"
    assert out["tool"] == "workflow_graph_mermaid"
    assert "message" in out


def test_runner_dry_run_plan_example_target() -> None:
    out = runner_dry_run_plan(target=EXAMPLE_TARGET, inputs_json=None)
    assert out["status"] == "ok"
    report = out["report"]
    assert report["schema"] == "replayt.validate_report.v1"
    assert report["ok"] is True
    assert report["target"] == EXAMPLE_TARGET


def test_runner_dry_run_plan_invalid_inputs_json() -> None:
    out = runner_dry_run_plan(target=EXAMPLE_TARGET, inputs_json="not-json")
    assert out["status"] == "invalid"
    errs = out["report"]["errors"]
    assert any("inputs" in e.lower() for e in errs)


def test_runner_dry_run_plan_bad_target() -> None:
    out = runner_dry_run_plan(target="definitely_not_a_module:wf", inputs_json=None)
    assert out["status"] == "error"
    assert out["tool"] == "runner_dry_run_plan"
    assert "message" in out


def test_persistence_list_run_events_reads_jsonl(tmp_path: Path) -> None:
    run_id = "test-run-jsonl"
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    event = {"seq": 1, "type": "unit_test_marker", "payload": {"x": 1}}
    (log_dir / f"{run_id}.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
    out = persistence_list_run_events(run_id=run_id, store_hint=str(log_dir))
    assert out["status"] == "ok"
    assert out["run_id"] == run_id
    assert out["event_count"] == 1
    assert out["events"][0]["type"] == "unit_test_marker"
    assert out["store"]["kind"] == "jsonl"


def test_persistence_list_run_events_invalid_run_id() -> None:
    out = persistence_list_run_events(run_id="../../etc/passwd", store_hint=None)
    assert out["status"] == "error"
    assert out["tool"] == "persistence_list_run_events"


def test_persistence_list_run_events_rejects_plain_file_store_hint(
    tmp_path: Path,
) -> None:
    f = tmp_path / "note.txt"
    f.write_text("x", encoding="utf-8")
    out = persistence_list_run_events(run_id="any-id", store_hint=str(f))
    assert out["status"] == "error"
    assert "plain file" in out["message"].lower()


def test_persistence_list_run_events_missing_sqlite(tmp_path: Path) -> None:
    missing = tmp_path / "nope.sqlite"
    out = persistence_list_run_events(run_id="rid-1", store_hint=str(missing))
    assert out["status"] == "error"
    assert "not found" in out["message"].lower()


def test_persistence_list_run_events_reads_sqlite(tmp_path: Path) -> None:
    run_id = "sqlite-run-1"
    db = tmp_path / "events.sqlite"
    st = SQLiteStore(db, read_only=False)
    try:
        st.append_event(
            run_id,
            ts="2020-01-01T00:00:00Z",
            typ="unit_test_marker",
            payload={"x": 2},
        )
    finally:
        st.close()
    out = persistence_list_run_events(run_id=run_id, store_hint=str(db))
    assert out["status"] == "ok"
    assert out["run_id"] == run_id
    assert out["event_count"] == 1
    assert out["events"][0]["type"] == "unit_test_marker"
    assert out["store"]["kind"] == "sqlite"
