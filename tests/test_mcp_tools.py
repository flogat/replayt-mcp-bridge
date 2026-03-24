"""Contract tests for the initial MCP tool surface (see docs/MCP_TOOLS.md)."""

from __future__ import annotations

import json
import logging
import textwrap
from pathlib import Path

import pytest
from replayt.persistence import SQLiteStore

from replayt_mcp_bridge import installed_replayt_version
from replayt_mcp_bridge.server import (
    _split_typed_store_hint,
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


def test_mcp_tools_doc_defines_store_hint_grammar() -> None:
    text = MCP_TOOLS_DOC.read_text(encoding="utf-8")
    assert "### store_hint grammar" in text
    assert "jsonl:" in text
    assert "sqlite:" in text


@pytest.mark.parametrize(
    ("hint", "expected_kind", "expected_path"),
    [
        ("jsonl:/tmp/logs", "jsonl", "/tmp/logs"),
        ("JSONL:  /tmp/logs", "jsonl", "/tmp/logs"),
        ("sqlite:./events.db", "sqlite", "./events.db"),
        ("SQLite:C:\\data\\db", "sqlite", "C:\\data\\db"),
    ],
)
def test_split_typed_store_hint_recognizes_prefixes(
    hint: str, expected_kind: str, expected_path: str
) -> None:
    kind, path = _split_typed_store_hint(hint)
    assert kind == expected_kind
    assert path == expected_path


def test_split_typed_store_hint_legacy_windows_drive_not_a_scheme() -> None:
    """Paths like ``C:\\foo`` must stay legacy so we do not treat the drive letter as a URI scheme."""

    hint = r"C:\replayt\logs"
    kind, path = _split_typed_store_hint(hint)
    assert kind is None
    assert path == hint


def test_split_typed_store_hint_unknown_prefix_is_legacy() -> None:
    kind, path = _split_typed_store_hint("file:///tmp/x")
    assert kind is None
    assert path == "file:///tmp/x"


def test_mcp_tools_doc_defines_correlation_error_spec() -> None:
    """Lock the integrator contract for correlation_id + mapped failure inventory (MCP_TOOLS.md)."""
    text = MCP_TOOLS_DOC.read_text(encoding="utf-8")
    assert "## Error response shape" in text
    assert (
        "### Specification: `correlation_id` (bounded structured errors backlog)"
        in text
    )
    assert "### Mapped failure paths (exception / branch inventory)" in text
    assert "### Unmapped exceptions (explicit)" in text
    assert "typer.BadParameter" in text
    assert "replayt_mcp_bridge.tool.unhandled_exception" in text


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
    assert isinstance(out.get("correlation_id"), str) and out["correlation_id"]


def test_mapped_tool_error_correlation_id_matches_structured_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Acceptance: same correlation_id on mapped tool result and stderr JSON for that call."""
    caplog.set_level(logging.INFO, logger="replayt_mcp_bridge.server")
    out = workflow_contract_snapshot(target="definitely_not_a_module:wf")
    assert out["status"] == "error"
    cid = out["correlation_id"]
    events = [json.loads(r.getMessage()) for r in caplog.records]
    begins = [e for e in events if e.get("event") == "replayt_mcp_bridge.tool.begin"]
    ends = [e for e in events if e.get("event") == "replayt_mcp_bridge.tool.end"]
    assert len(begins) == 1
    assert len(ends) == 1
    assert begins[0]["correlation_id"] == cid
    assert ends[0]["correlation_id"] == cid
    assert ends[0].get("status") == "error"


def test_unmapped_exception_keeps_correlation_in_logs_then_propagates(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unmapped failures are not converted to structured errors; logs still carry correlation_id."""
    from unittest.mock import MagicMock

    mock_wf = MagicMock()

    def _boom_contract() -> None:
        raise RuntimeError("deliberate_unmapped_contract")

    mock_wf.contract = _boom_contract
    monkeypatch.setattr("replayt_mcp_bridge.server.load_target", lambda _t: mock_wf)
    caplog.set_level(logging.INFO, logger="replayt_mcp_bridge.server")
    with pytest.raises(RuntimeError, match="deliberate_unmapped_contract"):
        workflow_contract_snapshot(target="ignored_target:wf")
    events = [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.getMessage().lstrip().startswith("{")
    ]
    begins = [e for e in events if e.get("event") == "replayt_mcp_bridge.tool.begin"]
    unhandled = [
        e
        for e in events
        if e.get("event") == "replayt_mcp_bridge.tool.unhandled_exception"
    ]
    assert len(begins) == 1
    assert len(unhandled) == 1
    assert begins[0]["correlation_id"] == unhandled[0]["correlation_id"]


def test_replayt_version_info_logs_tool_boundaries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="replayt_mcp_bridge.server")
    replayt_version_info()
    events = [json.loads(r.getMessage()) for r in caplog.records]
    kinds = {e["event"] for e in events}
    assert "replayt_mcp_bridge.tool.begin" in kinds
    assert "replayt_mcp_bridge.tool.end" in kinds
    for e in events:
        if e["event"] in (
            "replayt_mcp_bridge.tool.begin",
            "replayt_mcp_bridge.tool.end",
        ):
            assert isinstance(e.get("correlation_id"), str) and e["correlation_id"]


def test_replayt_echo_info_logs_exclude_message_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """docs/SECURITY.md: bridge logs tool name and status only, not MCP arguments."""
    caplog.set_level(logging.INFO, logger="replayt_mcp_bridge.server")
    secret_like = "replayt_mcp_bridge_test_secret_payload_7f3a9c"
    replayt_echo(message=secret_like)
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert secret_like not in blob
    for r in caplog.records:
        assert secret_like not in repr(r.__dict__)
        payload = json.loads(r.getMessage())
        assert secret_like not in json.dumps(payload)


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
    assert out.get("correlation_id")


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
    assert out.get("correlation_id")


def test_runner_dry_run_plan_strict_graph_changes_outcome(tmp_path: Path) -> None:
    """strict_graph=True promotes multi-state / no-edge graphs from warning-only to errors."""
    wf_py = tmp_path / "two_state_no_edges.py"
    wf_py.write_text(
        textwrap.dedent(
            """
            from replayt.workflow import Workflow

            wf = Workflow("mcp_strict_graph_contract")
            wf.set_initial("a")

            @wf.step("a")
            def a(ctx):
                return "b"

            @wf.step("b")
            def b(ctx):
                return None
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    target = str(wf_py)
    loose = runner_dry_run_plan(target=target, inputs_json=None, strict_graph=False)
    assert loose["status"] == "ok"
    strict = runner_dry_run_plan(target=target, inputs_json=None, strict_graph=True)
    assert strict["status"] == "invalid"
    assert any("strict graph" in e.lower() for e in strict["report"]["errors"])


def test_runner_dry_run_plan_metadata_json_invalid() -> None:
    out = runner_dry_run_plan(
        target=EXAMPLE_TARGET,
        inputs_json=None,
        metadata_json="not-json",
    )
    assert out["status"] == "invalid"
    errs = out["report"]["errors"]
    assert any("metadata" in e.lower() for e in errs)


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
    assert out.get("correlation_id")


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


def test_persistence_list_run_events_typed_jsonl_prefix(tmp_path: Path) -> None:
    run_id = "typed-jsonl-run"
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / f"{run_id}.jsonl").write_text(
        json.dumps({"seq": 1, "type": "unit_test_marker", "payload": {}}) + "\n",
        encoding="utf-8",
    )
    out = persistence_list_run_events(run_id=run_id, store_hint=f"JSONL:{log_dir}")
    assert out["status"] == "ok"
    assert out["event_count"] == 1
    assert out["store"]["kind"] == "jsonl"


def test_persistence_list_run_events_typed_sqlite_prefix_without_suffix(
    tmp_path: Path,
) -> None:
    run_id = "typed-sqlite-nosuf"
    db = tmp_path / "events_db"
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
    out = persistence_list_run_events(run_id=run_id, store_hint=f"sqlite:{db}")
    assert out["status"] == "ok"
    assert out["store"]["kind"] == "sqlite"


def test_persistence_list_run_events_typed_prefix_empty_path_rejected() -> None:
    out = persistence_list_run_events(run_id="any", store_hint="jsonl:")
    assert out["status"] == "error"
    assert out["tool"] == "persistence_list_run_events"
    assert "empty" in out["message"].lower()


def test_persistence_list_run_events_jsonl_prefix_rejects_existing_file(
    tmp_path: Path,
) -> None:
    db = tmp_path / "only.sqlite"
    st = SQLiteStore(db, read_only=False)
    try:
        st.append_event(
            "x",
            ts="2020-01-01T00:00:00Z",
            typ="unit_test_marker",
            payload={},
        )
    finally:
        st.close()
    out = persistence_list_run_events(run_id="x", store_hint=f"jsonl:{db}")
    assert out["status"] == "error"
    assert "jsonl:" in out["message"].lower()
    assert "directory" in out["message"].lower()


def test_persistence_list_run_events_omitted_store_hint_bypasses_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Omitted ``store_hint`` uses ``resolve_log_dir``; allowlist checks only explicit hints."""

    allow_root = tmp_path / "allow_only_here"
    allow_root.mkdir()
    default_logs = tmp_path / "actual_default_logs"
    default_logs.mkdir()
    run_id = "r-omit-hint"
    (default_logs / f"{run_id}.jsonl").write_text(
        json.dumps({"seq": 1, "type": "unit_test_marker", "payload": {}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS", str(allow_root))

    def fake_resolve_log_dir(_default: Path) -> Path:
        return default_logs

    monkeypatch.setattr(
        "replayt_mcp_bridge.server.resolve_log_dir",
        fake_resolve_log_dir,
    )
    out = persistence_list_run_events(run_id=run_id, store_hint=None)
    assert out["status"] == "ok"
    assert out["event_count"] == 1
    assert Path(out["store"]["path"]) == default_logs


def test_persistence_list_run_events_allowlist_allows_under_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    nested = allowed / "logs"
    nested.mkdir()
    monkeypatch.setenv("REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS", str(allowed))
    run_id = "r-allow"
    (nested / f"{run_id}.jsonl").write_text(
        json.dumps({"seq": 1, "type": "unit_test_marker", "payload": {}}) + "\n",
        encoding="utf-8",
    )
    out = persistence_list_run_events(run_id=run_id, store_hint=str(nested))
    assert out["status"] == "ok"
    assert out["event_count"] == 1


def test_persistence_list_run_events_allowlist_allows_second_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.setenv(
        "REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS",
        f"{a},{b}",
    )
    run_id = "r2"
    log_b = b / "logs"
    log_b.mkdir()
    (log_b / f"{run_id}.jsonl").write_text(
        json.dumps({"seq": 1, "type": "unit_test_marker"}) + "\n",
        encoding="utf-8",
    )
    out = persistence_list_run_events(run_id=run_id, store_hint=str(log_b))
    assert out["status"] == "ok"


def test_persistence_list_run_events_allowlist_denies_outside_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "secret_probe_store_hint_9f2c1e"
    outside.mkdir()
    monkeypatch.setenv("REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS", str(allowed))
    out = persistence_list_run_events(run_id="any", store_hint=str(outside))
    assert out["status"] == "error"
    assert out["tool"] == "persistence_list_run_events"
    assert "replayt_surface" in out
    assert "secret_probe_store_hint_9f2c1e" not in out["message"]


def test_persistence_list_run_events_allowlist_rejection_logs_omit_probe_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    probe = tmp_path / "mcp_bridge_probe_path_aa11bb22"
    probe.mkdir()
    monkeypatch.setenv("REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS", str(allowed))
    caplog.set_level(logging.WARNING, logger="replayt_mcp_bridge.server")
    out = persistence_list_run_events(run_id="x", store_hint=str(probe))
    assert out["status"] == "error"
    assert out.get("correlation_id")
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "mcp_bridge_probe_path_aa11bb22" not in blob
    rejected = [
        json.loads(r.getMessage())
        for r in caplog.records
        if "store_hint.rejected" in r.getMessage()
    ]
    assert len(rejected) == 1
    assert rejected[0]["correlation_id"] == out["correlation_id"]


def test_persistence_list_run_events_allowlist_unusable_env_rejects_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS", ", , ")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    run_id = "r1"
    (log_dir / f"{run_id}.jsonl").write_text(
        json.dumps({"seq": 1, "type": "unit_test_marker"}) + "\n",
        encoding="utf-8",
    )
    out = persistence_list_run_events(run_id=run_id, store_hint=str(log_dir))
    assert out["status"] == "error"
    assert "refusing explicit store_hint" in out["message"].lower()


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
