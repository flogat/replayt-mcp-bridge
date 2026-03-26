"""Commands: seal, report, report-diff, export-run, bundle-export."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import typer

from replayt.cli.config import (
    DEFAULT_LOG_DIR,
    export_hook_timeout_seconds,
    get_project_config,
    parse_log_mode,
    resolve_forbid_log_mode_full,
    resolve_log_dir,
    resolve_log_mode_setting,
    resolve_policy_hook_context_json,
    resolve_redact_keys,
    seal_hook_timeout_seconds,
    verify_seal_hook_timeout_seconds,
)
from replayt.cli.display import (
    event_summary,
    parse_llm_model_filters,
    replay_html,
    run_attention_summary,
)
from replayt.cli.run_id_hints import echo_missing_run_hints
from replayt.cli.run_support import (
    export_hook_argv,
    export_hook_audit,
    first_jsonl_event_with_type,
    invoke_export_hook,
    invoke_seal_hook,
    invoke_verify_seal_hook,
    run_started_envelope_ts_from_events,
    run_started_envelope_ts_from_jsonl_path,
    run_started_hook_json_blobs_from_events,
    run_started_hook_json_blobs_from_jsonl_path,
    run_started_initial_state_from_events,
    run_started_initial_state_from_jsonl_path,
    run_started_inputs_json_from_events,
    run_started_inputs_json_from_jsonl_path,
    run_started_runtime_json_from_events,
    run_started_runtime_json_from_jsonl_path,
    seal_hook_argv,
    seal_hook_audit,
    verify_seal_hook_argv,
)
from replayt.cli.stores import read_store
from replayt.cli.targets import load_target
from replayt.export_run import events_to_jsonl_lines
from replayt.graph_export import workflow_to_mermaid
from replayt.persistence.jsonl import validate_run_id


def _exit_on_invalid_run_id(run_id: str) -> str:
    try:
        return validate_run_id(run_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def _privacy_hook_kwargs_from_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    log_mode, _ = resolve_log_mode_setting("redacted", cfg)
    forbid_full, _ = resolve_forbid_log_mode_full(cfg)
    redact_keys, _ = resolve_redact_keys(None, cfg)
    return {
        "log_mode": log_mode,
        "forbid_log_mode_full": forbid_full,
        "redact_keys": redact_keys,
    }


def _maybe_invoke_export_hook(
    *,
    run_id: str,
    export_kind: Literal["export_run", "bundle_export"],
    log_dir: Path,
    sqlite: Path | None,
    export_mode: str,
    out: Path,
    seal: bool,
    event_count: int,
    events: list[dict[str, Any]],
    cli_target: str | None = None,
    report_style: str | None = None,
    policy_hook_context_json: str | None = None,
) -> dict[str, Any] | None:
    cfg, _, _, _ = get_project_config()
    hook = export_hook_argv(cfg)
    if not hook:
        return None
    hook_timeout = export_hook_timeout_seconds(cfg)
    meta_j, tags_j, exp_j, wf_meta_j = run_started_hook_json_blobs_from_events(events)
    inputs_j = run_started_inputs_json_from_events(events)
    runtime_j = run_started_runtime_json_from_events(events)
    initial_st = run_started_initial_state_from_events(events)
    started_ts = run_started_envelope_ts_from_events(events)
    try:
        invoke_export_hook(
            hook,
            run_id=run_id,
            export_kind=export_kind,
            log_dir=log_dir,
            sqlite=sqlite,
            export_mode=export_mode,
            out=out,
            seal=seal,
            event_count=event_count,
            report_style=report_style,
            workflow_contract=_policy_workflow_contract_from_events(events),
            cli_target=cli_target,
            timeout_seconds=hook_timeout,
            metadata_json=meta_j,
            tags_json=tags_j,
            experiment_json=exp_j,
            workflow_meta_json=wf_meta_j,
            inputs_json=inputs_j,
            policy_hook_context_json=policy_hook_context_json,
            run_started_ts=started_ts,
            runtime_json=runtime_j,
            initial_state=initial_st,
            **_privacy_hook_kwargs_from_cfg(cfg),
        )
    except subprocess.TimeoutExpired as exc:
        lim = f"{hook_timeout}s" if hook_timeout is not None else "unlimited"
        typer.echo(
            f"export_hook timed out (limit {lim}); set REPLAYT_EXPORT_HOOK_TIMEOUT or "
            "export_hook_timeout in project config (<=0 for no limit).",
            err=True,
        )
        raise typer.Exit(code=1) from exc
    except subprocess.CalledProcessError as exc:
        typer.echo(f"export_hook exited with code {exc.returncode}", err=True)
        raise typer.Exit(code=1) from exc
    return export_hook_audit(cfg)


def _maybe_invoke_seal_hook(
    *,
    run_id: str,
    log_dir: Path,
    jsonl_path: Path,
    seal_out: Path,
    line_count: int,
    policy_hook_context_json: str | None = None,
) -> dict[str, Any] | None:
    cfg, _, _, _ = get_project_config()
    hook = seal_hook_argv(cfg)
    if not hook:
        return None
    hook_timeout = seal_hook_timeout_seconds(cfg)
    workflow_contract = _policy_workflow_contract_from_jsonl_path(jsonl_path)
    meta_j, tags_j, exp_j, wf_meta_j = run_started_hook_json_blobs_from_jsonl_path(jsonl_path)
    inputs_j = run_started_inputs_json_from_jsonl_path(jsonl_path)
    runtime_j = run_started_runtime_json_from_jsonl_path(jsonl_path)
    initial_st = run_started_initial_state_from_jsonl_path(jsonl_path)
    started_ts = run_started_envelope_ts_from_jsonl_path(jsonl_path)
    try:
        invoke_seal_hook(
            hook,
            run_id=run_id,
            log_dir=log_dir,
            jsonl_path=jsonl_path,
            seal_out=seal_out,
            line_count=line_count,
            workflow_contract=workflow_contract,
            timeout_seconds=hook_timeout,
            metadata_json=meta_j,
            tags_json=tags_j,
            experiment_json=exp_j,
            workflow_meta_json=wf_meta_j,
            inputs_json=inputs_j,
            policy_hook_context_json=policy_hook_context_json,
            run_started_ts=started_ts,
            runtime_json=runtime_j,
            initial_state=initial_st,
            **_privacy_hook_kwargs_from_cfg(cfg),
        )
    except subprocess.TimeoutExpired as exc:
        lim = f"{hook_timeout}s" if hook_timeout is not None else "unlimited"
        typer.echo(
            f"seal_hook timed out (limit {lim}); set REPLAYT_SEAL_HOOK_TIMEOUT or "
            "seal_hook_timeout in project config (<=0 for no limit).",
            err=True,
        )
        raise typer.Exit(code=1) from exc
    except subprocess.CalledProcessError as exc:
        typer.echo(f"seal_hook exited with code {exc.returncode}", err=True)
        raise typer.Exit(code=1) from exc
    return seal_hook_audit(cfg)


def _maybe_invoke_verify_seal_hook(
    *,
    run_id: str,
    log_dir: Path,
    manifest_path: Path,
    jsonl_path: Path,
    manifest_schema: str,
    line_count: int,
    file_sha256: str,
    policy_hook_context_json: str | None = None,
) -> None:
    cfg, _, _, _ = get_project_config()
    hook = verify_seal_hook_argv(cfg)
    if not hook:
        return
    hook_timeout = verify_seal_hook_timeout_seconds(cfg)
    workflow_contract = _policy_workflow_contract_from_jsonl_path(jsonl_path)
    meta_j, tags_j, exp_j, wf_meta_j = run_started_hook_json_blobs_from_jsonl_path(jsonl_path)
    inputs_j = run_started_inputs_json_from_jsonl_path(jsonl_path)
    runtime_j = run_started_runtime_json_from_jsonl_path(jsonl_path)
    initial_st = run_started_initial_state_from_jsonl_path(jsonl_path)
    started_ts = run_started_envelope_ts_from_jsonl_path(jsonl_path)
    try:
        invoke_verify_seal_hook(
            hook,
            run_id=run_id,
            log_dir=log_dir,
            manifest_path=manifest_path,
            jsonl_path=jsonl_path,
            manifest_schema=manifest_schema,
            line_count=line_count,
            file_sha256=file_sha256,
            workflow_contract=workflow_contract,
            timeout_seconds=hook_timeout,
            metadata_json=meta_j,
            tags_json=tags_j,
            experiment_json=exp_j,
            workflow_meta_json=wf_meta_j,
            inputs_json=inputs_j,
            policy_hook_context_json=policy_hook_context_json,
            run_started_ts=started_ts,
            runtime_json=runtime_j,
            initial_state=initial_st,
            **_privacy_hook_kwargs_from_cfg(cfg),
        )
    except subprocess.TimeoutExpired as exc:
        lim = f"{hook_timeout}s" if hook_timeout is not None else "unlimited"
        typer.echo(
            f"verify_seal_hook timed out (limit {lim}); set REPLAYT_VERIFY_SEAL_HOOK_TIMEOUT or "
            "verify_seal_hook_timeout in project config (<=0 for no limit).",
            err=True,
        )
        raise typer.Exit(code=1) from exc
    except subprocess.CalledProcessError as exc:
        typer.echo(f"verify_seal_hook exited with code {exc.returncode}", err=True)
        raise typer.Exit(code=1) from exc


def compute_seal_digests(raw: bytes) -> tuple[str, list[str], int]:
    """Return (file_sha256, per-line sha256 list, line_count) using the same rules as seal manifests."""

    file_digest = hashlib.sha256(raw).hexdigest()
    line_digests = [hashlib.sha256(line).hexdigest() for line in raw.splitlines(keepends=True)]
    return file_digest, line_digests, len(line_digests)


def _seal_manifest(
    *,
    schema: str,
    run_id: str,
    jsonl_path: str,
    raw: bytes,
    note: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    file_digest, line_digests, _n = compute_seal_digests(raw)
    manifest: dict[str, Any] = {
        "schema": schema,
        "run_id": run_id,
        "jsonl_path": jsonl_path,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "line_count": len(line_digests),
        "line_sha256": line_digests,
        "file_sha256": file_digest,
        "note": note,
    }
    if extra:
        manifest.update(extra)
    return manifest


def _export_run_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Compact run context copied into export manifests for audit handoff."""

    summary = event_summary(events)
    attention = run_attention_summary(events)
    return {
        **summary,
        "attention_kind": attention["attention_kind"],
        "attention_summary": attention["attention_summary"],
        "pending_approvals": attention["pending_approvals"],
    }


def _policy_workflow_contract_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Contract-shaped dict for policy-hook env (digest + name/version from ``run_started``)."""

    for event in events:
        if event.get("type") != "run_started":
            continue
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        name = payload.get("workflow_name")
        ver = payload.get("workflow_version")
        runtime = payload.get("runtime") or {}
        wf_rt = runtime.get("workflow") if isinstance(runtime, dict) else None
        digest = wf_rt.get("contract_sha256") if isinstance(wf_rt, dict) else None
        wf: dict[str, Any] = {}
        if name is not None:
            wf["name"] = name
        if ver is not None:
            wf["version"] = ver
        return {
            "contract_sha256": digest if isinstance(digest, str) else None,
            "workflow": wf,
        }
    return {"contract_sha256": None, "workflow": {}}


def _policy_workflow_contract_from_jsonl_path(path: Path) -> dict[str, Any]:
    """First ``run_started`` line in a JSONL file (standalone ``seal`` / ``verify-seal``)."""

    event = first_jsonl_event_with_type(path, event_type="run_started")
    if event is None:
        return {"contract_sha256": None, "workflow": {}}
    return _policy_workflow_contract_from_events([event])


def _workflow_contract_snapshot(
    *,
    events: list[dict[str, Any]],
    target: str | None,
    include_mermaid: bool,
) -> tuple[bytes | None, bytes | None, dict[str, Any] | None]:
    """Optional workflow contract/graph artifacts for export bundles."""

    if target is None:
        return None, None, None
    wf = load_target(target)
    contract = wf.contract()
    contract_bytes = (json.dumps(contract, indent=2) + "\n").encode("utf-8")
    mermaid_bytes = None
    if include_mermaid:
        mermaid_bytes = (workflow_to_mermaid(wf).rstrip() + "\n").encode("utf-8")
    recorded_sha = _export_run_summary(events).get("workflow_contract_sha256")
    snapshot_sha = contract.get("contract_sha256")
    matches_run_started: bool | None = None
    if isinstance(recorded_sha, str) and recorded_sha and isinstance(snapshot_sha, str) and snapshot_sha:
        matches_run_started = snapshot_sha == recorded_sha
    manifest_payload: dict[str, Any] = {
        "target": target,
        "file": "workflow.contract.json",
        "contract_sha256": snapshot_sha,
        "matches_run_started": matches_run_started,
    }
    if mermaid_bytes is not None:
        manifest_payload["mermaid_file"] = "workflow.mmd.txt"
    return contract_bytes, mermaid_bytes, manifest_payload


def cmd_seal(
    run_id: str = typer.Argument(..., help="Run id (JSONL file basename without .jsonl)."),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR, "--log-dir"),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Manifest output path (default: <log-dir>/<run_id>.seal.json).",
    ),
    policy_hook_context_json: str | None = typer.Option(
        None,
        "--policy-hook-context-json",
        help="Optional JSON object for REPLAYT_POLICY_HOOK_CONTEXT_JSON on seal_hook only.",
    ),
    output: Literal["text", "json"] = typer.Option("text", "--output", "-o", help="text or json."),
) -> None:
    """Write a SHA-256 manifest for a JSONL run log (best-effort audit helper; not cryptographic proof)."""

    log_dir = resolve_log_dir(log_dir, log_subdir)
    cfg, _, _, _ = get_project_config()
    try:
        policy_hook_canonical = resolve_policy_hook_context_json(policy_hook_context_json, cfg=cfg)
    except typer.BadParameter as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    try:
        safe_run_id = validate_run_id(run_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)

    log_root = log_dir.resolve()
    path = (log_dir / f"{safe_run_id}.jsonl").resolve()
    try:
        path.relative_to(log_root)
    except ValueError:
        typer.echo(
            f"Refusing to seal JSONL outside log directory: {path} is not under {log_root}",
            err=True,
        )
        raise typer.Exit(code=1)
    if not path.is_file():
        typer.echo(
            f"No JSONL at {path} (``seal`` applies to the primary JSONL file, not SQLite-only stores).",
            err=True,
        )
        raise typer.Exit(code=1)

    raw = path.read_bytes()
    manifest = _seal_manifest(
        schema="replayt.seal.v1",
        run_id=safe_run_id,
        jsonl_path=str(path.resolve()),
        raw=raw,
        note=(
            "Best-effort integrity record. Anyone who can write the log directory can replace "
            "both the JSONL and this manifest; use WORM storage or external signing for stronger guarantees."
        ),
    )
    out_path = out if out is not None else log_dir / f"{safe_run_id}.seal.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    policy_hook = _maybe_invoke_seal_hook(
        run_id=safe_run_id,
        log_dir=log_dir,
        jsonl_path=path,
        seal_out=out_path,
        line_count=int(manifest["line_count"]),
        policy_hook_context_json=policy_hook_canonical,
    )
    if policy_hook is not None:
        manifest["policy_hook"] = policy_hook
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if output == "json":
        typer.echo(json.dumps({**manifest, "manifest_path": str(out_path.resolve())}, indent=2))
    else:
        typer.echo(
            f"wrote {out_path} ({manifest['line_count']} lines, file_sha256={str(manifest['file_sha256'])[:12]}...)"
        )


_SEAL_VERIFY_SCHEMAS = frozenset({"replayt.seal.v1", "replayt.export_seal.v1"})


def cmd_verify_seal(
    run_id: str = typer.Argument(..., help="Run id (must match the manifest's run_id field)."),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR, "--log-dir"),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    manifest: Path | None = typer.Option(
        None,
        "--manifest",
        help="Seal JSON path (default: <log-dir>/<run_id>.seal.json).",
    ),
    jsonl: Path | None = typer.Option(
        None,
        "--jsonl",
        help="Override JSONL path (needed for extracted export/bundle manifests with relative jsonl_path).",
    ),
    policy_hook_context_json: str | None = typer.Option(
        None,
        "--policy-hook-context-json",
        help="Optional JSON object for REPLAYT_POLICY_HOOK_CONTEXT_JSON on verify_seal_hook only.",
    ),
    output: Literal["text", "json"] = typer.Option("text", "--output", "-o", help="text or json."),
) -> None:
    """Check that a JSONL run log still matches a prior ``replayt seal`` or export ``events.seal.json`` manifest."""

    log_dir = resolve_log_dir(log_dir, log_subdir)
    cfg, _, _, _ = get_project_config()
    try:
        policy_hook_canonical = resolve_policy_hook_context_json(policy_hook_context_json, cfg=cfg)
    except typer.BadParameter as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    try:
        safe_run_id = validate_run_id(run_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)

    manifest_path = manifest if manifest is not None else log_dir / f"{safe_run_id}.seal.json"
    if not manifest_path.is_file():
        typer.echo(f"No seal manifest at {manifest_path}", err=True)
        raise typer.Exit(code=1)

    try:
        data: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        typer.echo(f"Invalid JSON in manifest: {exc}", err=True)
        raise typer.Exit(code=1)

    schema = data.get("schema")
    if schema not in _SEAL_VERIFY_SCHEMAS:
        typer.echo(
            f"Unsupported manifest schema {schema!r} (expected one of {sorted(_SEAL_VERIFY_SCHEMAS)})",
            err=True,
        )
        raise typer.Exit(code=1)

    mid = data.get("run_id")
    if mid != safe_run_id:
        typer.echo(f"Manifest run_id {mid!r} does not match argument {safe_run_id!r}", err=True)
        raise typer.Exit(code=1)

    expected_file = data.get("file_sha256")
    expected_lines = data.get("line_sha256")
    expected_count = data.get("line_count")
    if not isinstance(expected_file, str) or not isinstance(expected_lines, list) or not isinstance(
        expected_count, int
    ):
        typer.echo("Manifest is missing file_sha256, line_sha256, or line_count", err=True)
        raise typer.Exit(code=1)
    if not all(isinstance(x, str) for x in expected_lines):
        typer.echo("Manifest line_sha256 must be a list of strings", err=True)
        raise typer.Exit(code=1)

    jsonl_path: Path | None = None
    if jsonl is not None:
        jsonl_path = jsonl.resolve()
    else:
        raw_jp = data.get("jsonl_path")
        if isinstance(raw_jp, str) and raw_jp.strip():
            cand = Path(raw_jp)
            if cand.is_file():
                jsonl_path = cand.resolve()
    if jsonl_path is None:
        log_root = log_dir.resolve()
        candidate = (log_dir / f"{safe_run_id}.jsonl").resolve()
        try:
            candidate.relative_to(log_root)
        except ValueError:
            typer.echo(
                f"Refusing to verify JSONL outside log directory: {candidate} is not under {log_root}",
                err=True,
            )
            raise typer.Exit(code=1)
        jsonl_path = candidate

    if not jsonl_path.is_file():
        typer.echo(f"No JSONL at {jsonl_path}", err=True)
        raise typer.Exit(code=1)

    raw = jsonl_path.read_bytes()
    file_digest, line_digests, line_count = compute_seal_digests(raw)

    mismatches: list[str] = []
    if file_digest != expected_file:
        mismatches.append("file_sha256")
    if line_count != expected_count:
        mismatches.append("line_count")
    if line_digests != expected_lines:
        mismatches.append("line_sha256")

    ok = not mismatches
    if ok:
        _maybe_invoke_verify_seal_hook(
            run_id=safe_run_id,
            log_dir=log_dir,
            manifest_path=manifest_path,
            jsonl_path=jsonl_path,
            manifest_schema=str(schema),
            line_count=line_count,
            file_sha256=file_digest,
            policy_hook_context_json=policy_hook_canonical,
        )
    if output == "json":
        report = {
            "schema": "replayt.verify_seal_report.v1",
            "ok": ok,
            "run_id": safe_run_id,
            "manifest_path": str(manifest_path.resolve()),
            "jsonl_path": str(jsonl_path),
            "manifest_schema": schema,
            "mismatches": mismatches,
        }
        typer.echo(json.dumps(report, indent=2))
        raise typer.Exit(code=0 if ok else 1)

    if ok:
        typer.echo(f"OK: {jsonl_path} matches {manifest_path}")
        return

    typer.echo(f"MISMATCH: {jsonl_path} does not match {manifest_path}", err=True)
    for name in mismatches:
        typer.echo(f"  - {name}", err=True)
    raise typer.Exit(code=1)


def cmd_report(
    run_id: str = typer.Argument(..., help="Run ID to generate report for"),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR, "--log-dir"),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, "--sqlite"),
    out: str | None = typer.Option(None, "--out", help="Output file path (default: stdout)"),
    style: Literal["default", "stakeholder", "support"] = typer.Option(
        "default",
        "--style",
        help="default (full), stakeholder, or support (failure/approval-first; omits tool/token sections).",
    ),
    report_format: Literal["html", "markdown"] = typer.Option(
        "html",
        "--format",
        help="html (self-contained page) or markdown (paste into tickets / chat).",
    ),
    llm_model: list[str] | None = typer.Option(
        None,
        "--llm-model",
        help=(
            "Repeat to OR-match logged model ids: limit structured outputs, parse-failure cards, "
            "and token totals to matching `llm_response` / structured-output lines "
            "(same rules as `replayt inspect --llm-model`)."
        ),
    ),
) -> None:
    """Generate a self-contained HTML or Markdown report for a run."""

    from replayt.cli.report_template import build_run_report_html, build_run_report_markdown

    llm_model_filters = parse_llm_model_filters(llm_model)

    cli_log_dir = log_dir
    log_dir = resolve_log_dir(log_dir, log_subdir)
    safe_run_id = _exit_on_invalid_run_id(run_id)
    with read_store(log_dir, sqlite) as store:
        events = store.load_events(safe_run_id)
    if not events:
        typer.echo(f"No events for run_id={safe_run_id!r}", err=True)
        echo_missing_run_hints(cli_log_dir=cli_log_dir, log_subdir=log_subdir, sqlite=sqlite)
        raise typer.Exit(code=1)

    if report_format == "markdown":
        report = build_run_report_markdown(safe_run_id, events, style=style, llm_model_filter=llm_model_filters)
    else:
        report = build_run_report_html(safe_run_id, events, style=style, llm_model_filter=llm_model_filters)

    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        typer.echo(f"Wrote report to {out_path}")
    else:
        typer.echo(report)


def cmd_report_diff(
    run_a: str = typer.Argument(..., metavar="RUN_A"),
    run_b: str = typer.Argument(..., metavar="RUN_B"),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR, "--log-dir"),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, "--sqlite"),
    out: str | None = typer.Option(None, "--out", help="Write HTML or Markdown here (default: stdout)."),
    report_format: Literal["html", "markdown"] = typer.Option(
        "html",
        "--format",
        help="html (self-contained page) or markdown (tickets / chat / docs).",
    ),
    style: Literal["default", "stakeholder", "support"] = typer.Option(
        "default",
        "--style",
        help="default (standard section order), stakeholder (attention hints + same order), "
        "or support (failure/approvals before context, for triage handoffs).",
    ),
    llm_model: list[str] | None = typer.Option(
        None,
        "--llm-model",
        help=(
            "Repeat to OR-match logged model ids: structured outputs, parse-failure rows, and token "
            "totals use the same slice as `replayt report --llm-model`."
        ),
    ),
) -> None:
    """Side-by-side comparison of two runs from local JSONL (no model calls)."""

    from replayt.cli.report_template import (
        build_report_diff_html,
        build_report_diff_markdown,
        collect_report_context,
    )

    llm_model_filters = parse_llm_model_filters(llm_model)

    cli_log_dir = log_dir
    log_dir = resolve_log_dir(log_dir, log_subdir)
    safe_a = _exit_on_invalid_run_id(run_a)
    safe_b = _exit_on_invalid_run_id(run_b)
    with read_store(log_dir, sqlite) as store:
        events_a = store.load_events(safe_a)
        events_b = store.load_events(safe_b)
    if not events_a:
        typer.echo(f"No events for run_id={safe_a!r}", err=True)
        echo_missing_run_hints(cli_log_dir=cli_log_dir, log_subdir=log_subdir, sqlite=sqlite)
        raise typer.Exit(code=1)
    if not events_b:
        typer.echo(f"No events for run_id={safe_b!r}", err=True)
        echo_missing_run_hints(cli_log_dir=cli_log_dir, log_subdir=log_subdir, sqlite=sqlite)
        raise typer.Exit(code=1)
    ctx_a = collect_report_context(events_a, llm_model_filter=llm_model_filters)
    ctx_b = collect_report_context(events_b, llm_model_filter=llm_model_filters)
    if report_format == "markdown":
        doc = build_report_diff_markdown(
            safe_a,
            safe_b,
            ctx_a,
            ctx_b,
            events_a=events_a,
            events_b=events_b,
            style=style,
            llm_model_filter=llm_model_filters,
        )
    else:
        doc = build_report_diff_html(
            safe_a,
            safe_b,
            ctx_a,
            ctx_b,
            events_a=events_a,
            events_b=events_b,
            style=style,
            llm_model_filter=llm_model_filters,
        )
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(doc, encoding="utf-8")
        typer.echo(f"Wrote {out_path}")
    else:
        typer.echo(doc)


def cmd_export_run(
    run_id: str = typer.Argument(...),
    out: Path = typer.Option(..., "--out", help="Output path (.tar.gz)."),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR, "--log-dir"),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, "--sqlite"),
    export_mode: str = typer.Option(
        "redacted",
        "--export-mode",
        case_sensitive=False,
        help="Sanitize copy: redacted | full | structured_only",
    ),
    target: str | None = typer.Option(
        None,
        "--target",
        help=(
            "Optional MODULE:wf / workflow.py to include workflow.contract.json; "
            ".py executes code - trusted only."
        ),
    ),
    seal: bool = typer.Option(
        False,
        "--seal",
        help="Include events.seal.json with SHA-256 digests for the exported events.jsonl.",
    ),
    policy_hook_context_json: str | None = typer.Option(
        None,
        "--policy-hook-context-json",
        help="Optional JSON object for REPLAYT_POLICY_HOOK_CONTEXT_JSON on export_hook only.",
    ),
) -> None:
    """Write a shareable .tar.gz: sanitized events.jsonl + manifest.json."""

    cli_log_dir = log_dir
    log_dir = resolve_log_dir(log_dir, log_subdir)
    cfg, _, _, _ = get_project_config()
    try:
        policy_hook_canonical = resolve_policy_hook_context_json(policy_hook_context_json, cfg=cfg)
    except typer.BadParameter as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    lm = parse_log_mode(export_mode)
    safe_run_id = _exit_on_invalid_run_id(run_id)
    with read_store(log_dir, sqlite) as store:
        events = store.load_events(safe_run_id)
    if not events:
        typer.echo(f"No events for run_id={safe_run_id!r}", err=True)
        echo_missing_run_hints(cli_log_dir=cli_log_dir, log_subdir=log_subdir, sqlite=sqlite)
        raise typer.Exit(code=1)

    policy_hook = _maybe_invoke_export_hook(
        run_id=safe_run_id,
        export_kind="export_run",
        log_dir=log_dir,
        sqlite=sqlite,
        export_mode=export_mode,
        out=out,
        seal=seal,
        event_count=len(events),
        events=events,
        cli_target=target,
        policy_hook_context_json=policy_hook_canonical,
    )
    lines = events_to_jsonl_lines(events, lm)
    bundle = b"".join(lines)
    digest = hashlib.sha256(bundle).hexdigest()
    run_summary = _export_run_summary(events)
    contract_bytes, _, contract_snapshot = _workflow_contract_snapshot(
        events=events,
        target=target,
        include_mermaid=False,
    )
    files = ["events.jsonl", "manifest.json"] + (["events.seal.json"] if seal else [])
    if contract_bytes is not None:
        files.append("workflow.contract.json")
    manifest: dict[str, Any] = {
        "schema": "replayt.export_bundle.v1",
        "run_id": safe_run_id,
        "export_mode": export_mode,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "line_count": len(lines),
        "files": files,
        "events_jsonl_sha256": digest,
        "run_summary": run_summary,
        "note": "Sanitized copy for sharing; not necessarily byte-identical to on-disk JSONL.",
    }
    if policy_hook is not None:
        manifest["policy_hook"] = policy_hook
    if contract_snapshot is not None:
        manifest["workflow_contract_snapshot"] = contract_snapshot
    man_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    seal_bytes: bytes | None = None
    if seal:
        seal_manifest = _seal_manifest(
            schema="replayt.export_seal.v1",
            run_id=safe_run_id,
            jsonl_path="events.jsonl",
            raw=bundle,
            note=(
                "Integrity record for the sanitized events.jsonl inside this export bundle. "
                "Verify the extracted file against this manifest; it does not attest to the original on-disk JSONL."
            ),
            extra={"export_mode": export_mode},
        )
        seal_bytes = json.dumps(seal_manifest, indent=2).encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w:gz") as tf:
        export_files: list[tuple[str, bytes]] = [
            ("events.jsonl", bundle),
            ("manifest.json", man_bytes),
        ]
        if contract_bytes is not None:
            export_files.append(("workflow.contract.json", contract_bytes))
        for name, body in export_files:
            ti = tarfile.TarInfo(name=f"{safe_run_id}/{name}")
            ti.size = len(body)
            tf.addfile(ti, io.BytesIO(body))
        if seal_bytes is not None:
            ti = tarfile.TarInfo(name=f"{safe_run_id}/events.seal.json")
            ti.size = len(seal_bytes)
            tf.addfile(ti, io.BytesIO(seal_bytes))
    typer.echo(f"wrote {out.resolve()} ({len(lines)} events, sha256={digest[:16]}...)")


def cmd_bundle_export(
    run_id: str = typer.Argument(...),
    out: Path = typer.Option(..., "--out", help="Output path (.tar.gz)."),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR, "--log-dir"),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, "--sqlite"),
    export_mode: str = typer.Option(
        "redacted",
        "--export-mode",
        case_sensitive=False,
        help="Sanitized events.jsonl: redacted | full | structured_only",
    ),
    report_style: Literal["default", "stakeholder", "support"] = typer.Option(
        "stakeholder",
        "--report-style",
        help="Which replayt report variant to include.",
    ),
    target: str | None = typer.Option(
        None,
        "--target",
        help=(
            "Optional MODULE:wf / workflow.py for workflow.contract.json and workflow.mmd.txt; "
            ".py executes code - trusted only."
        ),
    ),
    seal: bool = typer.Option(
        False,
        "--seal",
        help="Include events.seal.json with SHA-256 digests for the exported events.jsonl.",
    ),
    policy_hook_context_json: str | None = typer.Option(
        None,
        "--policy-hook-context-json",
        help="Optional JSON object for REPLAYT_POLICY_HOOK_CONTEXT_JSON on export_hook only.",
    ),
) -> None:
    """Write a stakeholder-oriented .tar.gz: HTML report, replay timeline HTML, sanitized events.jsonl, manifest."""

    from replayt.cli.report_template import build_run_report_html

    cli_log_dir = log_dir
    log_dir = resolve_log_dir(log_dir, log_subdir)
    cfg, _, _, _ = get_project_config()
    try:
        policy_hook_canonical = resolve_policy_hook_context_json(policy_hook_context_json, cfg=cfg)
    except typer.BadParameter as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    lm = parse_log_mode(export_mode)
    safe_run_id = _exit_on_invalid_run_id(run_id)
    with read_store(log_dir, sqlite) as store:
        events = store.load_events(safe_run_id)
    if not events:
        typer.echo(f"No events for run_id={safe_run_id!r}", err=True)
        echo_missing_run_hints(cli_log_dir=cli_log_dir, log_subdir=log_subdir, sqlite=sqlite)
        raise typer.Exit(code=1)

    policy_hook = _maybe_invoke_export_hook(
        run_id=safe_run_id,
        export_kind="bundle_export",
        log_dir=log_dir,
        sqlite=sqlite,
        export_mode=export_mode,
        out=out,
        seal=seal,
        event_count=len(events),
        events=events,
        cli_target=target,
        report_style=report_style,
        policy_hook_context_json=policy_hook_canonical,
    )
    report_html = build_run_report_html(safe_run_id, events, style=report_style)
    timeline_html = replay_html(safe_run_id, events, style=report_style)
    lines = events_to_jsonl_lines(events, lm)
    bundle = b"".join(lines)
    digest = hashlib.sha256(bundle).hexdigest()
    run_summary = _export_run_summary(events)
    contract_bytes, mermaid_bytes, contract_snapshot = _workflow_contract_snapshot(
        events=events,
        target=target,
        include_mermaid=True,
    )
    files = ["report.html", "timeline.html", "events.jsonl", "manifest.json"]
    if seal:
        files.append("events.seal.json")
    if contract_bytes is not None:
        files.append("workflow.contract.json")
    if mermaid_bytes is not None:
        files.append("workflow.mmd.txt")

    manifest: dict[str, Any] = {
        "schema": "replayt.bundle_export.v1",
        "run_id": safe_run_id,
        "export_mode": export_mode,
        "report_style": report_style,
        "timeline_style": report_style,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "events_jsonl_sha256": digest,
        "run_summary": run_summary,
        "note": "Stakeholder bundle: HTML views + sanitized JSONL; not necessarily byte-identical to on-disk JSONL.",
    }
    if policy_hook is not None:
        manifest["policy_hook"] = policy_hook
    if contract_snapshot is not None:
        manifest["workflow_contract_snapshot"] = contract_snapshot
    man_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    seal_bytes: bytes | None = None
    if seal:
        seal_manifest = _seal_manifest(
            schema="replayt.export_seal.v1",
            run_id=safe_run_id,
            jsonl_path="events.jsonl",
            raw=bundle,
            note=(
                "Integrity record for the sanitized events.jsonl inside this stakeholder bundle. "
                "Verify the extracted file against this manifest; it does not attest to the original on-disk JSONL."
            ),
            extra={
                "export_mode": export_mode,
                "report_style": report_style,
                "timeline_style": report_style,
            },
        )
        seal_bytes = json.dumps(seal_manifest, indent=2).encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    prefix = safe_run_id
    with tarfile.open(out, "w:gz") as tf:
        export_files = [
            ("report.html", report_html.encode("utf-8")),
            ("timeline.html", timeline_html.encode("utf-8")),
            ("events.jsonl", bundle),
            ("manifest.json", man_bytes),
        ]
        if contract_bytes is not None:
            export_files.append(("workflow.contract.json", contract_bytes))
        for name, body in export_files:
            ti = tarfile.TarInfo(name=f"{prefix}/{name}")
            ti.size = len(body)
            tf.addfile(ti, io.BytesIO(body))
        if seal_bytes is not None:
            ti = tarfile.TarInfo(name=f"{prefix}/events.seal.json")
            ti.size = len(seal_bytes)
            tf.addfile(ti, io.BytesIO(seal_bytes))
        if mermaid_bytes is not None:
            ti = tarfile.TarInfo(name=f"{prefix}/workflow.mmd.txt")
            ti.size = len(mermaid_bytes)
            tf.addfile(ti, io.BytesIO(mermaid_bytes))
    typer.echo(f"wrote {out.resolve()} ({len(lines)} events, sha256={digest[:16]}...)")


def register(app: typer.Typer) -> None:
    app.command("seal")(cmd_seal)
    app.command("verify-seal")(cmd_verify_seal)
    app.command("report")(cmd_report)
    app.command("report-diff")(cmd_report_diff)
    app.command("export-run")(cmd_export_run)
    app.command("bundle-export")(cmd_bundle_export)
