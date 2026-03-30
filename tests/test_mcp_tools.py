from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from mcp.types import TextContent
from replayt import LogLockError
from replayt.persistence import SQLiteStore
from replayt.persistence.jsonl import JSONLStore

import replayt_mcp_bridge.tools_health as tools_health_mod
from replayt_mcp_bridge.tools_health import (
    replayt_doctor,
    replayt_echo,
    replayt_version_info,
)
import replayt_mcp_bridge.persistence_support as persistence_support_mod
from replayt_mcp_bridge.tools_persistence import persistence_list_run_events
from replayt_mcp_bridge.observability import (
    parse_default_run_events_max_count,
    resolve_bridge_tool_timeout_seconds,
)
from replayt_mcp_bridge.mcp_instance import mcp
from replayt_mcp_bridge.tools_bounds import (
    LEN_JSON_BLOB,
    LEN_RUN_ID,
    LEN_TARGET_PATH,
)
from replayt_mcp_bridge.tools_workflow import (
    runner_dry_run_plan,
    workflow_contract_snapshot,
    workflow_graph_mermaid,
)
import replayt_mcp_bridge.tools_workflow as tools_workflow_mod
from replayt_mcp_bridge.utils import with_timeout


def _decode_mcp_tool_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        return result[1]
    if (
        isinstance(result, (list, tuple))
        and result
        and isinstance(result[0], TextContent)
    ):
        return json.loads(result[0].text)
    raise AssertionError(f"unexpected call_tool result type: {type(result)!r}")


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


def _structured_log_payloads(
    caplog: pytest.LogCaptureFixture,
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for rec in caplog.records:
        try:
            out.append(json.loads(rec.getMessage()))
        except json.JSONDecodeError:
            continue
    return out


def test_persistence_list_run_events_log_lock_error_correlates_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Mapped LogLockError: structured result, same correlation_id on tool.begin / tool.end, no traceback key."""

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    run_id = "lock-correlation-run"

    def _raise_lock(self: JSONLStore, _run_id: str) -> list[dict[str, object]]:
        raise LogLockError(
            "Could not lock JSONL log file. Use a single writer per run_id, close other processes using this log, or retry."
        )

    monkeypatch.setattr(JSONLStore, "load_events", _raise_lock)
    caplog.set_level(logging.INFO, logger="replayt_mcp_bridge.server")

    out = asyncio.run(
        persistence_list_run_events(run_id=run_id, store_hint=str(log_dir))
    )
    assert out["status"] == "error"
    assert out["tool"] == "persistence_list_run_events"
    assert out["replayt_surface"] == "replayt.persistence.jsonl (JSONL log lock)"
    cid = out["correlation_id"]
    assert isinstance(cid, str) and cid
    assert "traceback" not in out

    begin_cids: list[object] = []
    end_cids: list[object] = []
    for payload in _structured_log_payloads(caplog):
        if payload.get("event") == "replayt_mcp_bridge.tool.begin":
            assert payload.get("tool") == "persistence_list_run_events"
            begin_cids.append(payload.get("correlation_id"))
        elif payload.get("event") == "replayt_mcp_bridge.tool.end":
            assert payload.get("tool") == "persistence_list_run_events"
            assert payload.get("status") == "error"
            end_cids.append(payload.get("correlation_id"))

    assert begin_cids == [cid]
    assert end_cids == [cid]


def test_persistence_list_run_events_unmapped_exception_correlates_unhandled_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Unmapped raise: begin and unhandled_exception share correlation_id; exception propagates; no tool.end."""

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    run_id = "unmapped-prop-run"

    def _raise_runtime(self: JSONLStore, _run_id: str) -> list[dict[str, object]]:
        raise RuntimeError("deliberate unmapped persistence failure")

    monkeypatch.setattr(JSONLStore, "load_events", _raise_runtime)
    caplog.set_level(logging.INFO, logger="replayt_mcp_bridge.server")

    with pytest.raises(RuntimeError, match="deliberate unmapped persistence failure"):
        asyncio.run(persistence_list_run_events(run_id=run_id, store_hint=str(log_dir)))

    begin_cids: list[object] = []
    unhandled_cids: list[object] = []
    end_seen = False
    for payload in _structured_log_payloads(caplog):
        ev = payload.get("event")
        if ev == "replayt_mcp_bridge.tool.begin":
            begin_cids.append(payload.get("correlation_id"))
        elif ev == "replayt_mcp_bridge.tool.unhandled_exception":
            assert payload.get("tool") == "persistence_list_run_events"
            unhandled_cids.append(payload.get("correlation_id"))
        elif ev == "replayt_mcp_bridge.tool.end":
            if payload.get("tool") == "persistence_list_run_events":
                end_seen = True

    assert len(begin_cids) == 1
    assert len(unhandled_cids) == 1
    assert begin_cids[0] == unhandled_cids[0]
    assert not end_seen


def test_persistence_list_run_events_volume_limit_count_exceeded_correlates_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    run_id = "volume-count-run"
    big_list = [{"i": i} for i in range(5)]

    def _many_events(self: JSONLStore, _rid: str) -> list[dict[str, object]]:
        return big_list

    monkeypatch.setattr(JSONLStore, "load_events", _many_events)
    caplog.set_level(logging.INFO, logger="replayt_mcp_bridge.server")

    out = asyncio.run(
        persistence_list_run_events(
            run_id=run_id,
            store_hint=str(log_dir),
            max_events=2,
        )
    )
    assert out["status"] == "error"
    assert out["tool"] == "persistence_list_run_events"
    assert out["replayt_surface"] == "bridge_run_events_volume"
    cid = out["correlation_id"]
    assert isinstance(cid, str) and cid
    assert "traceback" not in out
    assert "5" in out["message"] and "2" in out["message"]

    vol_cids: list[object] = []
    for payload in _structured_log_payloads(caplog):
        if payload.get("event") == "replayt_mcp_bridge.run_events.volume_limit":
            vol_cids.append(payload.get("correlation_id"))
            assert payload.get("reason") == "event_count"
    assert vol_cids == [cid]

    begin_cids = [
        p.get("correlation_id")
        for p in _structured_log_payloads(caplog)
        if p.get("event") == "replayt_mcp_bridge.tool.begin"
        and p.get("tool") == "persistence_list_run_events"
    ]
    end_cids = [
        p.get("correlation_id")
        for p in _structured_log_payloads(caplog)
        if p.get("event") == "replayt_mcp_bridge.tool.end"
        and p.get("tool") == "persistence_list_run_events"
    ]
    assert begin_cids == [cid]
    assert end_cids == [cid]


def test_persistence_list_run_events_volume_limit_encoded_bytes_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    run_id = "volume-bytes-run"
    payload = [{"blob": "x" * 500}]

    def _fat_events(self: JSONLStore, _rid: str) -> list[dict[str, object]]:
        return payload

    monkeypatch.setattr(JSONLStore, "load_events", _fat_events)
    out = asyncio.run(
        persistence_list_run_events(
            run_id=run_id,
            store_hint=str(log_dir),
            max_total_bytes=80,
        )
    )
    assert out["status"] == "error"
    assert out["replayt_surface"] == "bridge_run_events_volume"
    assert "UTF-8" in out["message"] or "bytes" in out["message"]
    assert "traceback" not in out


def test_persistence_list_run_events_invalid_max_events_param(
    tmp_path: Path,
) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    out = asyncio.run(
        persistence_list_run_events(
            run_id="bad-param-run",
            store_hint=str(log_dir),
            max_events=0,
        )
    )
    assert out["status"] == "error"
    assert (
        out["replayt_surface"]
        == "EventStore.load_events (JSONL directory or SQLite file)"
    )
    assert "max_events" in out["message"]
    assert "traceback" not in out


def test_parse_default_run_events_max_count_invalid_env_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPLAYT_MCP_BRIDGE_RUN_EVENTS_MAX_COUNT", "not-an-int")
    assert parse_default_run_events_max_count() == 10_000


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


def test_persistence_list_run_events_allowlist_rejects_outside_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Explicit store_hint outside configured roots: structured error, generic message, stderr reason only."""

    allowed = tmp_path / "allowlisted_only"
    allowed.mkdir()
    probe_dir = tmp_path / "unique_probe_token_823f0837_denied"
    probe_dir.mkdir()
    db = probe_dir / "outside.sqlite"
    run_id = "allow-deny-outside"
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

    monkeypatch.setenv("REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS", str(allowed.resolve()))
    caplog.set_level(logging.INFO, logger="replayt_mcp_bridge.server")

    out = asyncio.run(persistence_list_run_events(run_id=run_id, store_hint=str(db)))
    assert out["status"] == "error"
    assert out["tool"] == "persistence_list_run_events"
    assert "traceback" not in out
    msg = out["message"]
    assert isinstance(msg, str)
    assert "unique_probe_token_823f0837_denied" not in msg
    assert str(probe_dir) not in msg
    assert str(db) not in msg

    rejected = [
        p
        for p in _structured_log_payloads(caplog)
        if p.get("event") == "replayt_mcp_bridge.store_hint.rejected"
    ]
    assert len(rejected) == 1
    assert rejected[0].get("reason") == "outside_allowlist"
    assert "unique_probe_token_823f0837_denied" not in json.dumps(rejected[0])
    assert str(probe_dir) not in json.dumps(rejected[0])


def test_persistence_list_run_events_allowlist_accepts_second_comma_separated_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_a = tmp_path / "first_root"
    root_b = tmp_path / "second_root"
    root_a.mkdir()
    root_b.mkdir()
    monkeypatch.setenv(
        "REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS",
        f"{root_a.resolve()},{root_b.resolve()}",
    )
    db = root_b / "under_second.sqlite"
    run_id = "sql-second-root"
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


def test_persistence_list_run_events_allowlist_unusable_env_rejects_explicit_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Non-empty env with no parseable absolute roots fails closed for explicit store_hint."""

    monkeypatch.setenv("REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS", ", , ,")
    db = tmp_path / "any.sqlite"
    run_id = "unusable-allow"
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

    caplog.set_level(logging.INFO, logger="replayt_mcp_bridge.server")
    out = asyncio.run(persistence_list_run_events(run_id=run_id, store_hint=str(db)))
    assert out["status"] == "error"
    assert out["tool"] == "persistence_list_run_events"
    assert "no valid absolute roots were parsed" in out["message"]
    assert str(db) not in out["message"]

    rejected = [
        p
        for p in _structured_log_payloads(caplog)
        if p.get("event") == "replayt_mcp_bridge.store_hint.rejected"
    ]
    assert len(rejected) == 1
    assert rejected[0].get("reason") == "allowlist_unusable"


def test_persistence_list_run_events_omitted_store_hint_bypasses_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitted store_hint uses resolve_log_dir only; allowlist does not apply."""

    allowed_only = tmp_path / "listed_root_only"
    allowed_only.mkdir()
    outside = tmp_path / "default_log_outside_listed_roots"
    log_dir = outside / "logs"
    log_dir.mkdir(parents=True)

    monkeypatch.setenv(
        "REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS", str(allowed_only.resolve())
    )

    def _fake_resolve(_cli_log_dir: Path, log_subdir: str | None = None) -> Path:
        return log_dir.resolve()

    monkeypatch.setattr(persistence_support_mod, "resolve_log_dir", _fake_resolve)
    monkeypatch.setattr(JSONLStore, "load_events", lambda self, _rid: [])

    out = asyncio.run(persistence_list_run_events(run_id="bypass-run"))
    assert out["status"] == "ok"
    assert out["store"]["kind"] == "jsonl"


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


def test_replayt_doctor_skip_connectivity_ok() -> None:
    out = asyncio.run(replayt_doctor())
    assert out["status"] == "ok"
    assert out.get("tool") == "replayt_doctor"
    doc = out["doctor"]
    assert isinstance(doc, dict)
    assert "doctor" in str(doc.get("schema", "")).lower()
    assert "checks" in doc
    assert isinstance(doc["checks"], list)
    assert "replayt_exit_code" in out


def test_replayt_doctor_bad_target_structured_error() -> None:
    out = asyncio.run(replayt_doctor(target="invalid_target_xyz"))
    assert out["status"] == "error"
    assert out["tool"] == "replayt_doctor"
    assert out["replayt_surface"] == "replayt doctor + replayt.cli.targets.load_target"
    assert "correlation_id" in out
    assert "traceback" not in out


def test_replayt_doctor_subprocess_non_json_maps_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _bad_stdout(_argv: list[str]) -> tuple[int, bytes, bytes]:
        return 0, b"not-json", b"typer failed"

    monkeypatch.setattr(
        tools_health_mod,
        "_run_replayt_doctor_subprocess",
        _bad_stdout,
    )
    out = asyncio.run(replayt_doctor())
    assert out["status"] == "error"
    assert out["tool"] == "replayt_doctor"
    assert out["replayt_surface"] == "replayt doctor (subprocess / parse)"


def test_replayt_doctor_timeout_on_slow_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _slow(_argv: list[str]) -> tuple[int, bytes, bytes]:
        await asyncio.sleep(1.0)
        return 0, b"{}", b""

    monkeypatch.setenv(
        "REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_REPLAYT_DOCTOR_SECONDS",
        "0.15",
    )
    monkeypatch.setattr(
        tools_health_mod,
        "_run_replayt_doctor_subprocess",
        _slow,
    )
    out = asyncio.run(replayt_doctor())
    assert out["status"] == "error"
    assert out["replayt_surface"] == "bridge_timeout"
    assert out["tool"] == "replayt_doctor"
    assert "correlation_id" in out


@pytest.mark.network
def test_replayt_doctor_connectivity_opt_in() -> None:
    """Runs ``replayt doctor`` without ``--skip-connectivity`` (outbound HTTP when configured).

    Excluded from default CI via ``pytest -m 'not network'``; run locally when you intend
    to exercise provider connectivity.
    """

    out = asyncio.run(replayt_doctor(skip_connectivity=False))
    assert out["status"] == "ok"
    assert "doctor" in out


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


def test_bridge_input_bounds_tier_a_over_limit_via_mcp() -> None:
    out = _decode_mcp_tool_result(
        asyncio.run(
            mcp.call_tool(
                "workflow_contract_snapshot",
                {"target": "x" * (LEN_TARGET_PATH + 1)},
            )
        )
    )
    assert out["status"] == "error"
    assert out["replayt_surface"] == "bridge_input_bounds"
    assert out["tool"] == "workflow_contract_snapshot"
    assert isinstance(out["correlation_id"], str) and out["correlation_id"]
    assert "traceback" not in out
    assert "target" in out["message"].lower()


def test_bridge_input_bounds_json_blob_over_limit_via_mcp() -> None:
    out = _decode_mcp_tool_result(
        asyncio.run(
            mcp.call_tool(
                "runner_dry_run_plan",
                {
                    "target": "a",
                    "inputs_json": "z" * (LEN_JSON_BLOB + 1),
                },
            )
        )
    )
    assert out["status"] == "error"
    assert out["replayt_surface"] == "bridge_input_bounds"
    assert out["tool"] == "runner_dry_run_plan"
    assert "correlation_id" in out
    assert "traceback" not in out


def test_bridge_input_bounds_tier_a_at_limit_success_via_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_load_target(t: str) -> Any:
        assert len(t) == LEN_TARGET_PATH
        wf = MagicMock()
        wf.contract.return_value = {}
        return wf

    monkeypatch.setattr(tools_workflow_mod, "load_target", fake_load_target)
    out = _decode_mcp_tool_result(
        asyncio.run(
            mcp.call_tool(
                "workflow_contract_snapshot",
                {"target": "y" * LEN_TARGET_PATH},
            )
        )
    )
    assert out["status"] == "ok"


def test_bridge_input_bounds_correlates_tool_lifecycle_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="replayt_mcp_bridge.server")
    out = _decode_mcp_tool_result(
        asyncio.run(
            mcp.call_tool(
                "workflow_graph_mermaid",
                {"target": "x" * (LEN_TARGET_PATH + 1)},
            )
        )
    )
    assert out["status"] == "error"
    cid = out["correlation_id"]
    begin = [
        p
        for p in _structured_log_payloads(caplog)
        if p.get("event") == "replayt_mcp_bridge.tool.begin"
        and p.get("tool") == "workflow_graph_mermaid"
    ]
    end = [
        p
        for p in _structured_log_payloads(caplog)
        if p.get("event") == "replayt_mcp_bridge.tool.end"
        and p.get("tool") == "workflow_graph_mermaid"
    ]
    assert len(begin) == 1 and len(end) == 1
    assert begin[0].get("correlation_id") == cid
    assert end[0].get("correlation_id") == cid
    assert end[0].get("status") == "error"


def test_list_tools_input_schema_includes_string_bounds() -> None:
    async def _run() -> None:
        tools = await mcp.list_tools()
        by_name = {t.name: t.inputSchema for t in tools}
        wcs = by_name["workflow_contract_snapshot"]["properties"]["target"]
        assert wcs["maxLength"] == LEN_TARGET_PATH
        ple = by_name["persistence_list_run_events"]["properties"]
        assert ple["run_id"]["maxLength"] == LEN_RUN_ID
        ev = ple["event_fields"]["anyOf"][0]
        assert ev["maxItems"] == 256
        assert ev["items"]["maxLength"] == 256
        rdr = by_name["runner_dry_run_plan"]["properties"]["inputs_json"]
        branches = rdr.get("anyOf", [rdr])
        max_lens = [
            b["maxLength"]
            for b in branches
            if isinstance(b, dict) and b.get("type") == "string" and "maxLength" in b
        ]
        assert LEN_JSON_BLOB in max_lens

    asyncio.run(_run())
