"""Subprocess timeout wrapper, run/resume policy hooks, and run exit helpers."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import typer

import replayt
from replayt.cli.targets import workflow_trust_audit_paths
from replayt.persistence.jsonl import validate_run_id
from replayt.runner import RunResult
from replayt.types import LogMode
from replayt.workflow import Workflow

RUN_RESULT_SCHEMA = "replayt.run_result.v1"
RUN_RESULT_STATUS_CONTRACT_SCHEMA = "replayt.run_result_status_contract.v1"
LOG_MODE_CONTRACT_SCHEMA = "replayt.log_mode_contract.v1"
JSONL_EVENT_TYPES_CONTRACT_SCHEMA = "replayt.jsonl_event_types_contract.v1"

# Injected into every trusted policy-hook subprocess; values match ``policy_hook_env_catalog`` hook keys.
POLICY_HOOK_NAME_ENV_VAR = "REPLAYT_POLICY_HOOK_NAME"


def _policy_hook_name_env(hook_key: str) -> dict[str, str]:
    return {POLICY_HOOK_NAME_ENV_VAR: hook_key}


def _privacy_contract_hook_env(
    *,
    log_mode: str,
    forbid_log_mode_full: bool,
    redact_keys: tuple[str, ...],
) -> dict[str, str]:
    """Non-secret logging contract for trusted policy hooks (audit without reading JSONL)."""

    keys = sorted(redact_keys, key=str.lower)
    return {
        "REPLAYT_LOG_MODE": log_mode,
        "REPLAYT_FORBID_LOG_MODE_FULL": "1" if forbid_log_mode_full else "0",
        "REPLAYT_REDACT_KEYS_JSON": json.dumps(keys),
    }


def _workflow_contract_hook_env(contract: dict[str, Any]) -> dict[str, str]:
    """Env vars shared by run_hook and resume_hook for workflow-surface policy checks."""

    wf = contract.get("workflow") if isinstance(contract.get("workflow"), dict) else {}
    sha = contract.get("contract_sha256")
    return {
        "REPLAYT_WORKFLOW_CONTRACT_SHA256": str(sha) if sha is not None else "",
        "REPLAYT_WORKFLOW_NAME": str(wf.get("name", "")),
        "REPLAYT_WORKFLOW_VERSION": str(wf.get("version", "")),
    }


def _workflow_entry_path_hook_env(target: str) -> dict[str, str]:
    """Absolute workflow entry path for policy hooks (``.py`` / YAML path or imported module ``__file__``)."""

    paths = workflow_trust_audit_paths(target)
    if not paths:
        return {}
    return {"REPLAYT_WORKFLOW_ENTRY_PATH": str(paths[0])}


def _run_started_payload_json_blobs(
    payload: dict[str, Any],
) -> tuple[str | None, str | None, str | None, str | None]:
    """JSON env strings for run_metadata / tags / experiment / workflow_meta (parity with ``run_hook``)."""

    def _dump(key: str) -> str | None:
        v = payload.get(key)
        if isinstance(v, dict):
            return json.dumps(v, sort_keys=True)
        return None

    wm = payload.get("workflow_meta")
    workflow_meta_json: str | None = None
    if isinstance(wm, dict) and wm:
        workflow_meta_json = json.dumps(wm, sort_keys=True)
    return _dump("run_metadata"), _dump("tags"), _dump("experiment"), workflow_meta_json


def workflow_meta_json_for_run_hook(wf: Workflow) -> str | None:
    """Sorted JSON matching ``run_started.workflow_meta`` (``Workflow.meta`` without ``llm_defaults``)."""

    meta = getattr(wf, "meta", None)
    if not isinstance(meta, dict) or not meta:
        return None
    meta_out = dict(meta)
    meta_out.pop("llm_defaults", None)
    if not meta_out:
        return None
    return json.dumps(meta_out, sort_keys=True)


def first_jsonl_event_with_type(path: Path, *, event_type: str) -> dict[str, Any] | None:
    """Return the first JSONL record whose ``type`` matches (streaming read).

    Stops at the first match so callers that only need early events (for example
    ``run_started``) do not load the entire append-only log into memory.
    Malformed UTF-8 is treated like an unreadable file (returns ``None``).
    """

    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    event = json.loads(s)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("type") == event_type:
                    return event
    except (OSError, UnicodeDecodeError):
        return None
    return None


def run_started_hook_json_blobs_from_events(
    events: list[dict[str, Any]],
) -> tuple[str | None, str | None, str | None, str | None]:
    """Read hook JSON blobs from the first ``run_started`` event."""

    for event in events:
        if event.get("type") != "run_started":
            continue
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            return (None, None, None, None)
        return _run_started_payload_json_blobs(payload)
    return (None, None, None, None)


def run_started_hook_json_blobs_from_jsonl_path(path: Path) -> tuple[str | None, str | None, str | None, str | None]:
    """Same as :func:`run_started_hook_json_blobs_from_events` but scans the JSONL file on disk."""

    event = first_jsonl_event_with_type(path, event_type="run_started")
    if event is None:
        return (None, None, None, None)
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        return (None, None, None, None)
    return _run_started_payload_json_blobs(payload)


def run_started_inputs_json_from_payload(payload: dict[str, Any]) -> str | None:
    """Canonical sorted JSON for ``run_started.inputs`` (object only); ``None`` means unreadable."""

    raw = payload.get("inputs")
    if raw is None:
        return json.dumps({}, sort_keys=True)
    if isinstance(raw, dict):
        return json.dumps(raw, sort_keys=True)
    return None


def run_started_inputs_json_from_events(events: list[dict[str, Any]]) -> str | None:
    """Sorted JSON env string for ``run_started.inputs`` from an in-memory timeline."""

    for event in events:
        if event.get("type") != "run_started":
            continue
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            return None
        return run_started_inputs_json_from_payload(payload)
    return None


def run_started_inputs_json_from_jsonl_path(path: Path) -> str | None:
    """Same as :func:`run_started_inputs_json_from_events` but scans the JSONL file on disk."""

    event = first_jsonl_event_with_type(path, event_type="run_started")
    if event is None:
        return None
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        return None
    return run_started_inputs_json_from_payload(payload)


def run_started_runtime_json_from_payload(payload: dict[str, Any]) -> str | None:
    """Canonical sorted JSON for ``run_started.runtime`` (object only); ``None`` if unreadable."""

    raw = payload.get("runtime")
    if raw is None:
        return json.dumps({}, sort_keys=True)
    if isinstance(raw, dict):
        return json.dumps(raw, sort_keys=True)
    return None


def run_started_runtime_json_from_events(events: list[dict[str, Any]]) -> str | None:
    """Sorted JSON env string for ``run_started.runtime`` from an in-memory timeline."""

    for event in events:
        if event.get("type") != "run_started":
            continue
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            return None
        return run_started_runtime_json_from_payload(payload)
    return None


def run_started_runtime_json_from_jsonl_path(path: Path) -> str | None:
    """Same as :func:`run_started_runtime_json_from_events` but scans the JSONL file on disk."""

    event = first_jsonl_event_with_type(path, event_type="run_started")
    if event is None:
        return None
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        return None
    return run_started_runtime_json_from_payload(payload)


def run_started_initial_state_from_payload(payload: dict[str, Any]) -> str | None:
    """Plain-string env value for ``run_started.initial_state``; ``None`` if *payload* is not a dict."""

    if not isinstance(payload, dict):
        return None
    v = payload.get("initial_state")
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return str(v)


def run_started_initial_state_from_events(events: list[dict[str, Any]]) -> str | None:
    """``initial_state`` string from the first ``run_started`` event in *events*."""

    for event in events:
        if event.get("type") != "run_started":
            continue
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            return None
        return run_started_initial_state_from_payload(payload)
    return None


def run_started_initial_state_from_jsonl_path(path: Path) -> str | None:
    """Same as :func:`run_started_initial_state_from_events` but scans the JSONL file on disk."""

    event = first_jsonl_event_with_type(path, event_type="run_started")
    if event is None:
        return None
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        return None
    return run_started_initial_state_from_payload(payload)


def run_started_envelope_ts_from_event(event: dict[str, Any]) -> str | None:
    """ISO 8601 ``ts`` from the JSONL envelope for a ``run_started`` line, when present."""

    if event.get("type") != "run_started":
        return None
    ts = event.get("ts")
    if isinstance(ts, str) and ts.strip():
        return ts.strip()
    return None


def run_started_envelope_ts_from_events(events: list[dict[str, Any]]) -> str | None:
    """``ts`` string from the first ``run_started`` event in *events*."""

    for event in events:
        if event.get("type") != "run_started":
            continue
        out = run_started_envelope_ts_from_event(event)
        if out is not None:
            return out
    return None


def run_started_envelope_ts_from_jsonl_path(path: Path) -> str | None:
    """Same as :func:`run_started_envelope_ts_from_events` but scans the JSONL file on disk."""

    event = first_jsonl_event_with_type(path, event_type="run_started")
    if event is None:
        return None
    return run_started_envelope_ts_from_event(event)


def _merge_run_started_ts_env(extra: dict[str, str], run_started_ts: str | None) -> None:
    if run_started_ts:
        extra["REPLAYT_RUN_STARTED_TS"] = run_started_ts


def _merge_optional_hook_json_env(
    extra: dict[str, str],
    *,
    metadata_json: str | None,
    tags_json: str | None,
    experiment_json: str | None,
    workflow_meta_json: str | None = None,
) -> None:
    if metadata_json is not None:
        extra["REPLAYT_RUN_METADATA_JSON"] = metadata_json
    if tags_json is not None:
        extra["REPLAYT_RUN_TAGS_JSON"] = tags_json
    if experiment_json is not None:
        extra["REPLAYT_RUN_EXPERIMENT_JSON"] = experiment_json
    if workflow_meta_json is not None:
        extra["REPLAYT_WORKFLOW_META_JSON"] = workflow_meta_json


def _merge_policy_hook_context_env(dst: dict[str, str], policy_hook_context_json: str | None) -> None:
    if policy_hook_context_json is not None:
        dst["REPLAYT_POLICY_HOOK_CONTEXT_JSON"] = policy_hook_context_json


def dry_check_suggested_command(
    *,
    target: str,
    inputs_json: str | None,
    log_dir: Path,
    sqlite: Path | None,
    log_mode: str,
    redact_keys: list[str] | None,
    tag: list[str] | None,
    dry_run: bool,
) -> str:
    parts = ["replayt", "run", target, "--log-dir", str(log_dir), "--log-mode", log_mode]
    if sqlite is not None:
        parts.extend(["--sqlite", str(sqlite)])
    if redact_keys:
        for key in redact_keys:
            parts.extend(["--redact-key", key])
    if inputs_json is not None:
        parts.extend(["--inputs-json", inputs_json])
    if tag:
        for t in tag:
            parts.extend(["--tag", t])
    if dry_run:
        parts.append("--dry-run")
    return " ".join(parts)


def _hook_argv(cfg: dict[str, Any], *, env_var: str, config_key: str) -> list[str] | None:
    env_hook = os.environ.get(env_var, "").strip()
    use_posix = os.name != "nt"
    if env_hook:
        return shlex.split(env_hook, posix=use_posix)
    hook = cfg.get(config_key)
    if isinstance(hook, list) and hook and all(isinstance(x, str) for x in hook):
        return [str(x) for x in hook]
    if isinstance(hook, str) and hook.strip():
        return shlex.split(hook.strip(), posix=use_posix)
    return None


def _hook_source(cfg: dict[str, Any], *, env_var: str, config_key: str) -> str:
    env_hook = os.environ.get(env_var, "").strip()
    if env_hook:
        return f"env:{env_var}"
    if cfg.get(config_key):
        return f"project_config:{config_key}"
    return "unset"


def _hook_audit_payload(argv: list[str] | None, *, source: str) -> dict[str, Any] | None:
    if not argv:
        return None
    raw_argv0 = str(argv[0]).strip()
    argv0 = Path(raw_argv0).name or raw_argv0
    return {
        "source": source,
        "argv0": argv0,
        "arg_count": len(argv),
    }


def run_hook_argv(cfg: dict[str, Any]) -> list[str] | None:
    """Argv for the optional pre-run policy subprocess (trusted project config / env only)."""

    return _hook_argv(cfg, env_var="REPLAYT_RUN_HOOK", config_key="run_hook")


def resume_hook_argv(cfg: dict[str, Any]) -> list[str] | None:
    """Argv for the optional resume gate subprocess (trusted project config / env only).

    ``resume_hook`` and ``REPLAYT_RESUME_HOOK`` are split with ``shlex`` and executed
    without a shell, equivalent to typing the same argv in a terminal: do not point them
    at untrusted input.
    """

    return _hook_argv(cfg, env_var="REPLAYT_RESUME_HOOK", config_key="resume_hook")


def export_hook_argv(cfg: dict[str, Any]) -> list[str] | None:
    """Argv for the optional pre-export policy subprocess (trusted project config / env only)."""

    return _hook_argv(cfg, env_var="REPLAYT_EXPORT_HOOK", config_key="export_hook")


def seal_hook_argv(cfg: dict[str, Any]) -> list[str] | None:
    """Argv for the optional pre-seal policy subprocess (trusted project config / env only)."""

    return _hook_argv(cfg, env_var="REPLAYT_SEAL_HOOK", config_key="seal_hook")


def verify_seal_hook_argv(cfg: dict[str, Any]) -> list[str] | None:
    """Argv for the optional post-verify policy subprocess (trusted project config / env only)."""

    return _hook_argv(cfg, env_var="REPLAYT_VERIFY_SEAL_HOOK", config_key="verify_seal_hook")


def run_hook_source(cfg: dict[str, Any]) -> str:
    return _hook_source(cfg, env_var="REPLAYT_RUN_HOOK", config_key="run_hook")


def resume_hook_source(cfg: dict[str, Any]) -> str:
    return _hook_source(cfg, env_var="REPLAYT_RESUME_HOOK", config_key="resume_hook")


def export_hook_source(cfg: dict[str, Any]) -> str:
    return _hook_source(cfg, env_var="REPLAYT_EXPORT_HOOK", config_key="export_hook")


def seal_hook_source(cfg: dict[str, Any]) -> str:
    return _hook_source(cfg, env_var="REPLAYT_SEAL_HOOK", config_key="seal_hook")


def run_hook_audit(cfg: dict[str, Any]) -> dict[str, Any] | None:
    return _hook_audit_payload(run_hook_argv(cfg), source=run_hook_source(cfg))


def resume_hook_audit(cfg: dict[str, Any]) -> dict[str, Any] | None:
    return _hook_audit_payload(resume_hook_argv(cfg), source=resume_hook_source(cfg))


def export_hook_audit(cfg: dict[str, Any]) -> dict[str, Any] | None:
    return _hook_audit_payload(export_hook_argv(cfg), source=export_hook_source(cfg))


def seal_hook_audit(cfg: dict[str, Any]) -> dict[str, Any] | None:
    return _hook_audit_payload(seal_hook_argv(cfg), source=seal_hook_source(cfg))


_SYSTEM_INTERPRETER_PREFIXES = (
    "/usr/bin/",
    "/bin/",
    "/sbin/",
    "/usr/sbin/",
    "/opt/homebrew/bin/",
    "/opt/hostedtoolcache/",
)


def _skip_system_interpreter_path_for_hook_audit(path: Path) -> bool:
    """True for interpreter binaries we should not treat as org-owned hook scripts."""

    try:
        resolved = path.resolve()
    except OSError:
        return False
    name = resolved.name.lower()
    if os.name == "nt":
        if name.startswith("python") and name.endswith(".exe"):
            return True
        return name in {"py.exe", "pytest.exe"}
    s = str(resolved)
    if not any(s.startswith(p) for p in _SYSTEM_INTERPRETER_PREFIXES):
        return False
    if name.startswith("python"):
        return True
    return name in {"bash", "sh", "zsh", "dash", "ksh", "py"}


def _policy_hook_argv_script_paths(argv: list[str] | None) -> list[Path]:
    """Pick filesystem script paths from hook argv for permission audits (best-effort)."""

    if not argv:
        return []
    out: list[Path] = []
    seen: set[str] = set()

    def add(raw: Path) -> bool:
        try:
            resolved = raw.expanduser().resolve()
        except OSError:
            return False
        if not resolved.is_file():
            return False
        if _skip_system_interpreter_path_for_hook_audit(resolved):
            return False
        key = str(resolved)
        if key in seen:
            return False
        seen.add(key)
        out.append(resolved)
        return True

    skip_final_raw0 = False
    raw0 = str(argv[0]).strip()
    if len(argv) >= 2:
        bin_name = Path(raw0).name.lower()
        if bin_name.startswith("python") or bin_name in {"py", "pytest"}:
            if add(Path(str(argv[1]).strip())):
                skip_final_raw0 = True
        elif bin_name in {"bash", "sh", "zsh", "dash"}:
            arg1 = str(argv[1]).strip()
            if arg1 and not arg1.startswith("-") and not arg1.startswith("("):
                if add(Path(arg1)):
                    skip_final_raw0 = True
    if raw0 and not skip_final_raw0:
        add(Path(raw0))
    return out


def policy_hook_trust_audit_paths_for_cfg(cfg: dict[str, Any]) -> list[Path]:
    """Resolve hook script paths for POSIX permission audits (mode bits only; no execution)."""

    merged: list[Path] = []
    seen: set[str] = set()
    for argv in (
        run_hook_argv(cfg),
        resume_hook_argv(cfg),
        export_hook_argv(cfg),
        seal_hook_argv(cfg),
        verify_seal_hook_argv(cfg),
    ):
        for p in _policy_hook_argv_script_paths(argv):
            key = str(p)
            if key not in seen:
                seen.add(key)
                merged.append(p)
    return merged


def invoke_hook(argv: list[str], *, extra_env: dict[str, str], timeout_seconds: float | None) -> None:
    """Run *argv* with extra env vars; *argv* must come from trusted config."""

    env = {
        **os.environ,
        **extra_env,
        "REPLAYT_REPLAYT_VERSION": replayt.__version__,
    }
    subprocess.run(
        argv,
        env=env,
        check=True,
        timeout=timeout_seconds,
        stdin=subprocess.DEVNULL,
    )


def invoke_run_hook(
    argv: list[str],
    *,
    target: str,
    run_id: str,
    log_dir: Path,
    log_mode: str,
    forbid_log_mode_full: bool,
    redact_keys: tuple[str, ...],
    dry_run: bool,
    resume: bool,
    sqlite: Path | None,
    workflow_contract: dict[str, Any],
    inputs_json: str | None,
    tags_json: str | None,
    metadata_json: str | None,
    experiment_json: str | None,
    workflow_meta_json: str | None = None,
    policy_hook_context_json: str | None = None,
    run_started_ts: str | None = None,
    runtime_json: str | None = None,
    initial_state: str | None = None,
    timeout_seconds: float | None,
) -> None:
    """Run a pre-run policy hook before the workflow starts writing events."""

    run_id = validate_run_id(run_id)
    root = log_dir.resolve()
    extra_env = {
        **_policy_hook_name_env("run_hook"),
        "REPLAYT_TARGET": target,
        "REPLAYT_RUN_ID": run_id,
        "REPLAYT_RUN_MODE": "resume" if resume else "run",
        "REPLAYT_LOG_DIR": str(root),
        "REPLAYT_RUN_JSONL": str((root / f"{run_id}.jsonl").resolve()),
        "REPLAYT_DRY_RUN": "1" if dry_run else "0",
        **_privacy_contract_hook_env(
            log_mode=log_mode,
            forbid_log_mode_full=forbid_log_mode_full,
            redact_keys=redact_keys,
        ),
        **_workflow_contract_hook_env(workflow_contract),
    }
    if sqlite is not None:
        extra_env["REPLAYT_SQLITE"] = str(sqlite.resolve())
    if inputs_json is not None:
        extra_env["REPLAYT_RUN_INPUTS_JSON"] = inputs_json
    if runtime_json is not None:
        extra_env["REPLAYT_RUN_STARTED_RUNTIME_JSON"] = runtime_json
    if initial_state is not None:
        extra_env["REPLAYT_RUN_STARTED_INITIAL_STATE"] = initial_state
    if tags_json is not None:
        extra_env["REPLAYT_RUN_TAGS_JSON"] = tags_json
    if metadata_json is not None:
        extra_env["REPLAYT_RUN_METADATA_JSON"] = metadata_json
    if experiment_json is not None:
        extra_env["REPLAYT_RUN_EXPERIMENT_JSON"] = experiment_json
    if workflow_meta_json is not None:
        extra_env["REPLAYT_WORKFLOW_META_JSON"] = workflow_meta_json
    extra_env.update(_workflow_entry_path_hook_env(target))
    _merge_policy_hook_context_env(extra_env, policy_hook_context_json)
    _merge_run_started_ts_env(extra_env, run_started_ts)
    invoke_hook(argv, extra_env=extra_env, timeout_seconds=timeout_seconds)


def invoke_resume_hook(
    argv: list[str],
    *,
    target: str,
    run_id: str,
    log_dir: Path,
    approval_id: str,
    reject: bool,
    log_mode: str,
    forbid_log_mode_full: bool,
    redact_keys: tuple[str, ...],
    workflow_contract: dict[str, Any],
    timeout_seconds: float | None,
    metadata_json: str | None = None,
    tags_json: str | None = None,
    experiment_json: str | None = None,
    workflow_meta_json: str | None = None,
    inputs_json: str | None = None,
    policy_hook_context_json: str | None = None,
    run_started_ts: str | None = None,
    runtime_json: str | None = None,
    initial_state: str | None = None,
) -> None:
    """Run *argv* with extra ``REPLAYT_*`` env vars; *argv* must come from trusted config."""

    run_id = validate_run_id(run_id)
    root = log_dir.resolve()
    extra = {
        **_policy_hook_name_env("resume_hook"),
        "REPLAYT_TARGET": target,
        "REPLAYT_RUN_ID": run_id,
        "REPLAYT_LOG_DIR": str(root),
        "REPLAYT_RUN_JSONL": str((root / f"{run_id}.jsonl").resolve()),
        "REPLAYT_APPROVAL_ID": approval_id,
        "REPLAYT_REJECT": "1" if reject else "0",
        **_privacy_contract_hook_env(
            log_mode=log_mode,
            forbid_log_mode_full=forbid_log_mode_full,
            redact_keys=redact_keys,
        ),
        **_workflow_contract_hook_env(workflow_contract),
    }
    _merge_optional_hook_json_env(
        extra,
        metadata_json=metadata_json,
        tags_json=tags_json,
        experiment_json=experiment_json,
        workflow_meta_json=workflow_meta_json,
    )
    if inputs_json is not None:
        extra["REPLAYT_RUN_INPUTS_JSON"] = inputs_json
    if runtime_json is not None:
        extra["REPLAYT_RUN_STARTED_RUNTIME_JSON"] = runtime_json
    if initial_state is not None:
        extra["REPLAYT_RUN_STARTED_INITIAL_STATE"] = initial_state
    extra.update(_workflow_entry_path_hook_env(target))
    _merge_policy_hook_context_env(extra, policy_hook_context_json)
    _merge_run_started_ts_env(extra, run_started_ts)
    invoke_hook(argv, extra_env=extra, timeout_seconds=timeout_seconds)


def invoke_export_hook(
    argv: list[str],
    *,
    run_id: str,
    export_kind: str,
    log_dir: Path,
    sqlite: Path | None,
    export_mode: str,
    out: Path,
    seal: bool,
    event_count: int,
    report_style: str | None,
    workflow_contract: dict[str, Any],
    cli_target: str | None,
    log_mode: str,
    forbid_log_mode_full: bool,
    redact_keys: tuple[str, ...],
    timeout_seconds: float | None,
    metadata_json: str | None = None,
    tags_json: str | None = None,
    experiment_json: str | None = None,
    workflow_meta_json: str | None = None,
    inputs_json: str | None = None,
    policy_hook_context_json: str | None = None,
    run_started_ts: str | None = None,
    runtime_json: str | None = None,
    initial_state: str | None = None,
) -> None:
    """Run *argv* before ``export-run`` / ``bundle-export`` writes the archive; *argv* is trusted config only."""

    extra: dict[str, str] = {
        **_policy_hook_name_env("export_hook"),
        "REPLAYT_RUN_ID": run_id,
        "REPLAYT_EXPORT_KIND": export_kind,
        "REPLAYT_LOG_DIR": str(log_dir.resolve()),
        "REPLAYT_EXPORT_MODE": export_mode,
        "REPLAYT_EXPORT_OUT": str(out.resolve()),
        "REPLAYT_EXPORT_SEAL": "1" if seal else "0",
        "REPLAYT_EXPORT_EVENT_COUNT": str(event_count),
        **_privacy_contract_hook_env(
            log_mode=log_mode,
            forbid_log_mode_full=forbid_log_mode_full,
            redact_keys=redact_keys,
        ),
        **_workflow_contract_hook_env(workflow_contract),
    }
    if sqlite is not None:
        extra["REPLAYT_SQLITE"] = str(sqlite.resolve())
    if report_style is not None:
        extra["REPLAYT_BUNDLE_REPORT_STYLE"] = report_style
    if cli_target:
        extra["REPLAYT_TARGET"] = cli_target
        extra.update(_workflow_entry_path_hook_env(cli_target))
    _merge_optional_hook_json_env(
        extra,
        metadata_json=metadata_json,
        tags_json=tags_json,
        experiment_json=experiment_json,
        workflow_meta_json=workflow_meta_json,
    )
    if inputs_json is not None:
        extra["REPLAYT_RUN_INPUTS_JSON"] = inputs_json
    if runtime_json is not None:
        extra["REPLAYT_RUN_STARTED_RUNTIME_JSON"] = runtime_json
    if initial_state is not None:
        extra["REPLAYT_RUN_STARTED_INITIAL_STATE"] = initial_state
    _merge_policy_hook_context_env(extra, policy_hook_context_json)
    _merge_run_started_ts_env(extra, run_started_ts)
    invoke_hook(argv, extra_env=extra, timeout_seconds=timeout_seconds)


def invoke_seal_hook(
    argv: list[str],
    *,
    run_id: str,
    log_dir: Path,
    jsonl_path: Path,
    seal_out: Path,
    line_count: int,
    workflow_contract: dict[str, Any],
    log_mode: str,
    forbid_log_mode_full: bool,
    redact_keys: tuple[str, ...],
    timeout_seconds: float | None,
    metadata_json: str | None = None,
    tags_json: str | None = None,
    experiment_json: str | None = None,
    workflow_meta_json: str | None = None,
    inputs_json: str | None = None,
    policy_hook_context_json: str | None = None,
    run_started_ts: str | None = None,
    runtime_json: str | None = None,
    initial_state: str | None = None,
) -> None:
    """Run *argv* before ``replayt seal`` writes the manifest; *argv* is trusted config only."""

    extra = {
        **_policy_hook_name_env("seal_hook"),
        "REPLAYT_RUN_ID": run_id,
        "REPLAYT_LOG_DIR": str(log_dir.resolve()),
        "REPLAYT_SEAL_JSONL": str(jsonl_path.resolve()),
        "REPLAYT_SEAL_OUT": str(seal_out.resolve()),
        "REPLAYT_SEAL_LINE_COUNT": str(line_count),
        **_privacy_contract_hook_env(
            log_mode=log_mode,
            forbid_log_mode_full=forbid_log_mode_full,
            redact_keys=redact_keys,
        ),
        **_workflow_contract_hook_env(workflow_contract),
    }
    _merge_optional_hook_json_env(
        extra,
        metadata_json=metadata_json,
        tags_json=tags_json,
        experiment_json=experiment_json,
        workflow_meta_json=workflow_meta_json,
    )
    if inputs_json is not None:
        extra["REPLAYT_RUN_INPUTS_JSON"] = inputs_json
    if runtime_json is not None:
        extra["REPLAYT_RUN_STARTED_RUNTIME_JSON"] = runtime_json
    if initial_state is not None:
        extra["REPLAYT_RUN_STARTED_INITIAL_STATE"] = initial_state
    _merge_policy_hook_context_env(extra, policy_hook_context_json)
    _merge_run_started_ts_env(extra, run_started_ts)
    invoke_hook(argv, extra_env=extra, timeout_seconds=timeout_seconds)


def invoke_verify_seal_hook(
    argv: list[str],
    *,
    run_id: str,
    log_dir: Path,
    manifest_path: Path,
    jsonl_path: Path,
    manifest_schema: str,
    line_count: int,
    file_sha256: str,
    workflow_contract: dict[str, Any],
    log_mode: str,
    forbid_log_mode_full: bool,
    redact_keys: tuple[str, ...],
    timeout_seconds: float | None,
    metadata_json: str | None = None,
    tags_json: str | None = None,
    experiment_json: str | None = None,
    workflow_meta_json: str | None = None,
    inputs_json: str | None = None,
    policy_hook_context_json: str | None = None,
    run_started_ts: str | None = None,
    runtime_json: str | None = None,
    initial_state: str | None = None,
) -> None:
    """Run *argv* after ``replayt verify-seal`` digests match; *argv* is trusted config only."""

    extra = {
        **_policy_hook_name_env("verify_seal_hook"),
        "REPLAYT_RUN_ID": run_id,
        "REPLAYT_LOG_DIR": str(log_dir.resolve()),
        "REPLAYT_VERIFY_SEAL_MANIFEST": str(manifest_path.resolve()),
        "REPLAYT_VERIFY_SEAL_JSONL": str(jsonl_path.resolve()),
        "REPLAYT_VERIFY_SEAL_SCHEMA": manifest_schema,
        "REPLAYT_VERIFY_SEAL_LINE_COUNT": str(line_count),
        "REPLAYT_VERIFY_SEAL_FILE_SHA256": file_sha256,
        **_privacy_contract_hook_env(
            log_mode=log_mode,
            forbid_log_mode_full=forbid_log_mode_full,
            redact_keys=redact_keys,
        ),
        **_workflow_contract_hook_env(workflow_contract),
    }
    _merge_optional_hook_json_env(
        extra,
        metadata_json=metadata_json,
        tags_json=tags_json,
        experiment_json=experiment_json,
        workflow_meta_json=workflow_meta_json,
    )
    if inputs_json is not None:
        extra["REPLAYT_RUN_INPUTS_JSON"] = inputs_json
    if runtime_json is not None:
        extra["REPLAYT_RUN_STARTED_RUNTIME_JSON"] = runtime_json
    if initial_state is not None:
        extra["REPLAYT_RUN_STARTED_INITIAL_STATE"] = initial_state
    _merge_policy_hook_context_env(extra, policy_hook_context_json)
    _merge_run_started_ts_env(extra, run_started_ts)
    invoke_hook(argv, extra_env=extra, timeout_seconds=timeout_seconds)


def build_policy_hook_env_catalog() -> dict[str, Any]:
    """Stable machine-readable contract for trusted policy-hook subprocesses (CI / MCP wrappers)."""

    hooks: dict[str, dict[str, Any]] = {
        "run_hook": {
            "argv_env": "REPLAYT_RUN_HOOK",
            "argv_config_key": "run_hook",
            "injected_env_vars": sorted(
                {
                    "REPLAYT_DRY_RUN",
                    "REPLAYT_FORBID_LOG_MODE_FULL",
                    "REPLAYT_LOG_DIR",
                    "REPLAYT_LOG_MODE",
                    "REPLAYT_POLICY_HOOK_CONTEXT_JSON",
                    "REPLAYT_POLICY_HOOK_NAME",
                    "REPLAYT_REDACT_KEYS_JSON",
                    "REPLAYT_REPLAYT_VERSION",
                    "REPLAYT_RUN_EXPERIMENT_JSON",
                    "REPLAYT_RUN_ID",
                    "REPLAYT_RUN_INPUTS_JSON",
                    "REPLAYT_RUN_JSONL",
                    "REPLAYT_RUN_METADATA_JSON",
                    "REPLAYT_RUN_MODE",
                    "REPLAYT_RUN_STARTED_INITIAL_STATE",
                    "REPLAYT_RUN_STARTED_RUNTIME_JSON",
                    "REPLAYT_RUN_STARTED_TS",
                    "REPLAYT_RUN_TAGS_JSON",
                    "REPLAYT_SQLITE",
                    "REPLAYT_TARGET",
                    "REPLAYT_WORKFLOW_CONTRACT_SHA256",
                    "REPLAYT_WORKFLOW_ENTRY_PATH",
                    "REPLAYT_WORKFLOW_META_JSON",
                    "REPLAYT_WORKFLOW_NAME",
                    "REPLAYT_WORKFLOW_VERSION",
                }
            ),
        },
        "resume_hook": {
            "argv_env": "REPLAYT_RESUME_HOOK",
            "argv_config_key": "resume_hook",
            "injected_env_vars": sorted(
                {
                    "REPLAYT_APPROVAL_ID",
                    "REPLAYT_FORBID_LOG_MODE_FULL",
                    "REPLAYT_LOG_DIR",
                    "REPLAYT_LOG_MODE",
                    "REPLAYT_POLICY_HOOK_CONTEXT_JSON",
                    "REPLAYT_POLICY_HOOK_NAME",
                    "REPLAYT_REJECT",
                    "REPLAYT_REDACT_KEYS_JSON",
                    "REPLAYT_REPLAYT_VERSION",
                    "REPLAYT_RUN_EXPERIMENT_JSON",
                    "REPLAYT_RUN_ID",
                    "REPLAYT_RUN_INPUTS_JSON",
                    "REPLAYT_RUN_JSONL",
                    "REPLAYT_RUN_METADATA_JSON",
                    "REPLAYT_RUN_STARTED_INITIAL_STATE",
                    "REPLAYT_RUN_STARTED_RUNTIME_JSON",
                    "REPLAYT_RUN_STARTED_TS",
                    "REPLAYT_RUN_TAGS_JSON",
                    "REPLAYT_TARGET",
                    "REPLAYT_WORKFLOW_CONTRACT_SHA256",
                    "REPLAYT_WORKFLOW_ENTRY_PATH",
                    "REPLAYT_WORKFLOW_META_JSON",
                    "REPLAYT_WORKFLOW_NAME",
                    "REPLAYT_WORKFLOW_VERSION",
                }
            ),
        },
        "export_hook": {
            "argv_env": "REPLAYT_EXPORT_HOOK",
            "argv_config_key": "export_hook",
            "injected_env_vars": sorted(
                {
                    "REPLAYT_BUNDLE_REPORT_STYLE",
                    "REPLAYT_EXPORT_EVENT_COUNT",
                    "REPLAYT_EXPORT_KIND",
                    "REPLAYT_EXPORT_MODE",
                    "REPLAYT_EXPORT_OUT",
                    "REPLAYT_EXPORT_SEAL",
                    "REPLAYT_FORBID_LOG_MODE_FULL",
                    "REPLAYT_LOG_DIR",
                    "REPLAYT_LOG_MODE",
                    "REPLAYT_POLICY_HOOK_CONTEXT_JSON",
                    "REPLAYT_POLICY_HOOK_NAME",
                    "REPLAYT_REDACT_KEYS_JSON",
                    "REPLAYT_REPLAYT_VERSION",
                    "REPLAYT_RUN_EXPERIMENT_JSON",
                    "REPLAYT_RUN_ID",
                    "REPLAYT_RUN_INPUTS_JSON",
                    "REPLAYT_RUN_METADATA_JSON",
                    "REPLAYT_RUN_STARTED_INITIAL_STATE",
                    "REPLAYT_RUN_STARTED_RUNTIME_JSON",
                    "REPLAYT_RUN_STARTED_TS",
                    "REPLAYT_RUN_TAGS_JSON",
                    "REPLAYT_SQLITE",
                    "REPLAYT_TARGET",
                    "REPLAYT_WORKFLOW_CONTRACT_SHA256",
                    "REPLAYT_WORKFLOW_ENTRY_PATH",
                    "REPLAYT_WORKFLOW_META_JSON",
                    "REPLAYT_WORKFLOW_NAME",
                    "REPLAYT_WORKFLOW_VERSION",
                }
            ),
        },
        "seal_hook": {
            "argv_env": "REPLAYT_SEAL_HOOK",
            "argv_config_key": "seal_hook",
            "injected_env_vars": sorted(
                {
                    "REPLAYT_FORBID_LOG_MODE_FULL",
                    "REPLAYT_LOG_DIR",
                    "REPLAYT_LOG_MODE",
                    "REPLAYT_POLICY_HOOK_CONTEXT_JSON",
                    "REPLAYT_POLICY_HOOK_NAME",
                    "REPLAYT_REDACT_KEYS_JSON",
                    "REPLAYT_REPLAYT_VERSION",
                    "REPLAYT_RUN_EXPERIMENT_JSON",
                    "REPLAYT_RUN_ID",
                    "REPLAYT_RUN_INPUTS_JSON",
                    "REPLAYT_RUN_METADATA_JSON",
                    "REPLAYT_RUN_STARTED_INITIAL_STATE",
                    "REPLAYT_RUN_STARTED_RUNTIME_JSON",
                    "REPLAYT_RUN_STARTED_TS",
                    "REPLAYT_RUN_TAGS_JSON",
                    "REPLAYT_SEAL_JSONL",
                    "REPLAYT_SEAL_LINE_COUNT",
                    "REPLAYT_SEAL_OUT",
                    "REPLAYT_WORKFLOW_CONTRACT_SHA256",
                    "REPLAYT_WORKFLOW_META_JSON",
                    "REPLAYT_WORKFLOW_NAME",
                    "REPLAYT_WORKFLOW_VERSION",
                }
            ),
        },
        "verify_seal_hook": {
            "argv_env": "REPLAYT_VERIFY_SEAL_HOOK",
            "argv_config_key": "verify_seal_hook",
            "injected_env_vars": sorted(
                {
                    "REPLAYT_FORBID_LOG_MODE_FULL",
                    "REPLAYT_LOG_DIR",
                    "REPLAYT_LOG_MODE",
                    "REPLAYT_POLICY_HOOK_CONTEXT_JSON",
                    "REPLAYT_POLICY_HOOK_NAME",
                    "REPLAYT_REDACT_KEYS_JSON",
                    "REPLAYT_REPLAYT_VERSION",
                    "REPLAYT_RUN_EXPERIMENT_JSON",
                    "REPLAYT_RUN_ID",
                    "REPLAYT_RUN_INPUTS_JSON",
                    "REPLAYT_RUN_METADATA_JSON",
                    "REPLAYT_RUN_STARTED_INITIAL_STATE",
                    "REPLAYT_RUN_STARTED_RUNTIME_JSON",
                    "REPLAYT_RUN_STARTED_TS",
                    "REPLAYT_RUN_TAGS_JSON",
                    "REPLAYT_VERIFY_SEAL_FILE_SHA256",
                    "REPLAYT_VERIFY_SEAL_JSONL",
                    "REPLAYT_VERIFY_SEAL_LINE_COUNT",
                    "REPLAYT_VERIFY_SEAL_MANIFEST",
                    "REPLAYT_VERIFY_SEAL_SCHEMA",
                    "REPLAYT_WORKFLOW_CONTRACT_SHA256",
                    "REPLAYT_WORKFLOW_META_JSON",
                    "REPLAYT_WORKFLOW_NAME",
                    "REPLAYT_WORKFLOW_VERSION",
                }
            ),
        },
    }
    return {
        "subprocess_stdin": "devnull",
        "hooks": {name: hooks[name] for name in sorted(hooks)},
    }


def build_internal_run_argv(
    *,
    target: str,
    run_id: str | None,
    inputs_json: str | None,
    log_dir: Path,
    sqlite: Path | None,
    log_mode: str,
    redact_keys: list[str] | None,
    tag: list[str] | None,
    resume: bool,
    dry_run: bool,
    output: str,
    metadata_json: str | None = None,
    experiment_json: str | None = None,
    policy_hook_context_json: str | None = None,
    strict_graph: bool = False,
    replayt_internal_junit_xml: Path | None = None,
    replayt_internal_github_summary: bool = False,
    replayt_internal_summary_json: Path | None = None,
) -> list[str]:
    """Argv for ``python -m replayt.cli.main`` (must not include ``--timeout``; parent enforces that)."""

    argv = ["run", target, "--log-dir", str(log_dir), "--log-mode", log_mode, "--output", output]
    if redact_keys:
        for key in redact_keys:
            argv += ["--redact-key", key]
    if run_id:
        argv += ["--run-id", run_id]
    if inputs_json is not None:
        argv += ["--inputs-json", inputs_json]
    if sqlite is not None:
        argv += ["--sqlite", str(sqlite)]
    if tag:
        for t in tag:
            argv += ["--tag", t]
    if metadata_json is not None:
        argv += ["--metadata-json", metadata_json]
    if experiment_json is not None:
        argv += ["--experiment-json", experiment_json]
    if policy_hook_context_json is not None:
        argv += ["--policy-hook-context-json", policy_hook_context_json]
    if resume:
        argv.append("--resume")
    if dry_run:
        argv.append("--dry-run")
    if strict_graph:
        argv.append("--strict-graph")
    if replayt_internal_junit_xml is not None:
        argv += ["--replayt-internal-junit-xml", str(replayt_internal_junit_xml.resolve())]
    if replayt_internal_github_summary:
        argv.append("--replayt-internal-github-summary")
    if replayt_internal_summary_json is not None:
        argv += ["--replayt-internal-summary-json", str(replayt_internal_summary_json.resolve())]
    return argv


def subprocess_env_child() -> dict[str, str]:
    """Environment for isolated ``replayt run`` children (timeout). Ensures ``replayt`` is importable."""

    env = {**os.environ, "REPLAYT_SUBPROCESS_RUN": "1"}
    for p in sys.path:
        if not p:
            continue
        try:
            root = Path(p)
            for candidate in (root, root / "src"):
                if Path(candidate, "replayt", "__init__.py").is_file():
                    prev = env.get("PYTHONPATH", "")
                    cand = str(candidate)
                    env["PYTHONPATH"] = f"{cand}{os.pathsep}{prev}" if prev else cand
                    return env
        except OSError:
            continue
    return env


def exit_code_for_run_result(result: RunResult) -> int:
    """CLI exit codes: 0 completed, 1 failed, 2 paused (waiting for approval or similar)."""

    if result.status == "completed":
        return 0
    if result.status == "paused":
        return 2
    return 1


def build_cli_stdio_contract() -> dict[str, Any]:
    """When the CLI may read the parent process stdin (subprocess / MCP wrappers).

    Policy hooks always use ``stdin=subprocess.DEVNULL``; see ``policy_hook_env_catalog``.
    """

    return {
        "recommended_subprocess_stdin": "devnull",
        "reads_utf8_json_object_from_stdin": {
            "subcommands": sorted(["ci", "doctor", "run", "validate"]),
            "triggers": sorted(
                [
                    "cli:--inputs-file=-",
                    "cli:--inputs-json=@-",
                    "env:REPLAYT_INPUTS_FILE=-",
                ]
            ),
            "encoding": "utf-8",
            "empty_stdin_json": "object",
        },
        "note": (
            "Unless you intentionally forward a UTF-8 JSON object for one of the triggers above, pass "
            "stdin=subprocess.DEVNULL (or equivalent) so a host-attached stdin stream does not become "
            "the workflow inputs payload."
        ),
    }


TRUST_PROFILE_MACHINE_FLAGS: dict[str, dict[str, bool]] = {
    "doctor_preflight": {
        "appends_run_timeline": False,
        "executes_workflow_runner": False,
        "may_invoke_trusted_policy_hooks": False,
        "may_probe_default_llm_http": True,
        "writes_scaffold_paths": False,
        "writes_seal_manifest": False,
    },
    "graph_validate_short_circuit": {
        "appends_run_timeline": False,
        "executes_workflow_runner": False,
        "may_invoke_trusted_policy_hooks": False,
        "may_probe_default_llm_http": False,
        "writes_scaffold_paths": False,
        "writes_seal_manifest": False,
    },
    "inventory_read_only": {
        "appends_run_timeline": False,
        "executes_workflow_runner": False,
        "may_invoke_trusted_policy_hooks": False,
        "may_probe_default_llm_http": False,
        "writes_scaffold_paths": False,
        "writes_seal_manifest": False,
    },
    "seal_manifest_write": {
        "appends_run_timeline": False,
        "executes_workflow_runner": False,
        "may_invoke_trusted_policy_hooks": True,
        "may_probe_default_llm_http": False,
        "writes_scaffold_paths": False,
        "writes_seal_manifest": True,
    },
    "try_copy_scaffold": {
        "appends_run_timeline": False,
        "executes_workflow_runner": False,
        "may_invoke_trusted_policy_hooks": False,
        "may_probe_default_llm_http": False,
        "writes_scaffold_paths": True,
        "writes_seal_manifest": False,
    },
    "verify_seal_compare": {
        "appends_run_timeline": False,
        "executes_workflow_runner": False,
        "may_invoke_trusted_policy_hooks": True,
        "may_probe_default_llm_http": False,
        "writes_scaffold_paths": False,
        "writes_seal_manifest": False,
    },
    "workflow_run_execute": {
        "appends_run_timeline": True,
        "executes_workflow_runner": True,
        "may_invoke_trusted_policy_hooks": True,
        "may_probe_default_llm_http": False,
        "writes_scaffold_paths": False,
        "writes_seal_manifest": False,
    },
}


CLI_JSON_STDOUT_TRUST_PROFILES: dict[str, str] = {
    "inventory_read_only": (
        "Does not invoke Runner.run, run_hook, or seal/verify_seal hooks; does not append JSONL run timelines "
        "or write seal manifests. Subcommands that take a TARGET still import or load that workflow module or "
        "file to build contracts or validation payloads."
    ),
    "graph_validate_short_circuit": (
        "Loads the workflow and validates the graph and optional inputs metadata, then exits before run_hook "
        "and before Runner.run (same early-return path as replayt validate for --dry-check on run, ci, and try)."
    ),
    "workflow_run_execute": (
        "Runs Runner.run (or an isolated subprocess with the same outcome). May append JSONL/SQLite, may "
        "invoke run_hook before execution, and may call the configured LLM unless the CLI uses --dry-run "
        "placeholder mode."
    ),
    "seal_manifest_write": (
        "Hashes the run JSONL and writes <run_id>.seal.json beside it; may invoke seal_hook before the "
        "manifest is written."
    ),
    "verify_seal_compare": (
        "Re-hashes JSONL and compares digests to a manifest; may invoke verify_seal_hook after a successful "
        "match (hook failure turns exit code 1)."
    ),
    "doctor_preflight": (
        "Install, config, and path readiness checks; may contact the default LLM provider unless "
        "--skip-connectivity."
    ),
    "try_copy_scaffold": (
        "Copies packaged example files into --copy-to; does not invoke Runner.run."
    ),
}


def _stdout_json_route(
    trust_profile: str,
    *,
    route_id: str,
    schema_key: str,
    option: str,
    short: str | None = None,
    equals: str | None = None,
    when: str | None = None,
    boolean_flag: bool | None = None,
    exit_codes_with_json_on_stdout: tuple[int, ...] | None = None,
    positional_required: tuple[str, ...] = (),
    positional_optional: tuple[str, ...] = (),
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "route_id": route_id,
        "option": option,
        "schema_key": schema_key,
        "trust_profile": trust_profile,
        "positional_required": list(positional_required),
        "positional_optional": list(positional_optional),
    }
    if short is not None:
        row["short"] = short
    if equals is not None:
        row["equals"] = equals
    if when is not None:
        row["when"] = when
    if boolean_flag is not None:
        row["boolean_flag"] = boolean_flag
    codes = (0,) if exit_codes_with_json_on_stdout is None else tuple(sorted(set(exit_codes_with_json_on_stdout)))
    row["exit_codes_with_json_on_stdout"] = list(codes)
    return row


# Full payload schema ids for each cli_json_stdout_contract route (must match cli_machine_readable_schemas).
_CLI_JSON_STDOUT_ROUTE_SCHEMA_BY_KEY: dict[str, str] = {
    "config_report": "replayt.config_report.v1",
    "diff_report": "replayt.diff_report.v1",
    "doctor_report": "replayt.doctor_report.v1",
    "init_templates": "replayt.init_templates.v1",
    "inspect_report": "replayt.inspect_report.v1",
    "runs_report": "replayt.runs_report.v1",
    "run_result": RUN_RESULT_SCHEMA,
    "seal": "replayt.seal.v1",
    "stats_report": "replayt.stats_report.v1",
    "try_copy": "replayt.try_copy.v1",
    "try_examples": "replayt.try_examples.v1",
    "try_print_snippet": "replayt.try_print_snippet.v1",
    "validate_report": "replayt.validate_report.v1",
    "verify_seal_report": "replayt.verify_seal_report.v1",
    "version_report": "replayt.version_report.v1",
    "workflow_contract": "replayt.workflow_contract.v1",
    "workflow_contract_check": "replayt.workflow_contract_check.v1",
}


def build_cli_json_stdout_contract() -> dict[str, Any]:
    """Machine-readable map of JSON-on-stdout routes (``replayt version --format json``).

    ``schema_key`` names an entry in the sibling ``cli_machine_readable_schemas`` object on the same
    version report; each route row also sets ``schema`` to the same ``replayt.*.v1`` string for
    subprocess hosts. Omitted: commands whose stdout is HTML/Markdown/text only, tarball writers, and
    file sinks such as ``--summary-json``.
    """

    inv = "inventory_read_only"
    dry = "graph_validate_short_circuit"
    runx = "workflow_run_execute"

    contract: dict[str, Any] = {
        "note": (
            "Maps subcommands to flags that select JSON on stdout. Each schema_key matches a key under "
            "cli_machine_readable_schemas on this report; each route row also duplicates the resolved "
            "replayt.*.v1 id as schema so subprocess and MCP wrappers can map argv to the expected stdout "
            "payload type without a second lookup. Each route includes route_id: a stable globally unique "
            "string (dot-separated; Typer subcommand names use underscores instead of hyphens in the first "
            "segment) for MCP tool registration, allowlist diffs, and upgrade guards without relying on "
            "array order under subcommands. Each route lists exit_codes_with_json_on_stdout: sorted "
            "exit codes that can occur after replayt wrote that schema's JSON object to stdout (Typer "
            "pre-dispatch failures and many pre-callback validation errors typically exit without JSON on "
            "stdout; see typer_pre_dispatch_phase). positional_required and positional_optional are ordered "
            "Typer positional argv slots (stable names: TARGET, RUN_ID, RUN_A, RUN_B) for MCP tool arg "
            "schemas; they are not full argv templates (see rejection blocklist). Optional TARGET may still "
            "resolve from env or project config (cli_run_defaults_contract). "
            "Each route includes trust_profile, an index into "
            "trust_profiles for subprocess/MCP allowlists. replayt log-schema always prints the bundled "
            "Draft JSON Schema for one JSONL line (stdout) and is not tied to cli_machine_readable_schemas. "
            "replayt ci still prints a one-line stderr reminder when --output json is used. See "
            "subprocess_stream_semantics for stdout vs stderr expectations when wrapping the CLI, and "
            "typer_pre_dispatch_phase for Typer usage failures vs workflow pause (both may use exit code 2). "
            "trust_profile_machine_flags mirrors trust_profiles with stable booleans for argv allowlists "
            "(MCP tools, CI gates) without parsing prose."
        ),
        "subprocess_stream_semantics": {
            "stdout": {
                "encoding": "utf-8",
                "when_json_route_active": (
                    "Exactly one JSON value is written to stdout (a single object) before the process exits; "
                    "no NDJSON prefix or trailing non-JSON lines."
                ),
            },
            "stderr": {
                "may_contain_human_or_progress_hints_when_stdout_is_json": True,
                "documented_cases": [
                    {
                        "subcommand": "ci",
                        "summary": (
                            "Always emits a one-line exit-code legend on stderr before the run (text or JSON "
                            "stdout); parse JSON from stdout only."
                        ),
                    },
                ],
            },
            "wrapper_note": (
                "Subprocess and MCP hosts should capture stdout and stderr separately; use json.loads on "
                "stdout after exit when the JSON route flags in subcommands match, and treat stderr as "
                "diagnostic unless you explicitly parse it."
            ),
        },
        "typer_pre_dispatch_phase": {
            "summary": (
                "Typer may exit before a subcommand callback runs (unknown subcommand, missing positional "
                "arguments, unknown options, or mutually exclusive flags). Those errors are human-oriented "
                "and usually print to stderr; stdout may be empty."
            ),
            "typical_exit_code": 2,
            "exit_code_overlap": {
                "summary": (
                    "The same numeric exit code (2) is used when replayt run / ci / resume / try pauses for "
                    "approval after the workflow runner starts. Subprocess wrappers cannot rely on exit code "
                    "alone for those subcommands."
                ),
                "disambiguation_for_json_stdout_routes": (
                    "When --output json is in effect on run, ci, or try and the process pauses for approval, "
                    "stdout is one JSON object with schema replayt.run_result.v1 and status paused. When Typer "
                    "rejects argv before dispatch, stdout is typically not parseable JSON; read stderr for "
                    "Usage / Error panels."
                ),
                "disambiguation_for_resume_text_stdout": (
                    "replayt resume does not offer --output json; pauses still exit 2 after printing text lines "
                    "such as status=paused. Typer argv failures exit 2 with Usage / Error on stderr and usually "
                    "without those runner summary lines on stdout."
                ),
                "disambiguation_for_text_mode": (
                    "Prefer JSON routes on run, ci, and try for automation. In text mode, Typer failures usually "
                    "include 'Usage:' or boxed Error text on stderr."
                ),
            },
        },
        "trust_profiles": dict(sorted(CLI_JSON_STDOUT_TRUST_PROFILES.items())),
        "trust_profile_machine_flags": dict(sorted(TRUST_PROFILE_MACHINE_FLAGS.items())),
        "subcommands": {
            "ci": [
                _stdout_json_route(
                    dry,
                    route_id="ci.output_json.validate_report_with_dry_check",
                    option="--output",
                    short="-o",
                    equals="json",
                    schema_key="validate_report",
                    when="with --dry-check (graph/input validation only)",
                    exit_codes_with_json_on_stdout=(0, 1),
                    positional_optional=("TARGET",),
                ),
                _stdout_json_route(
                    runx,
                    route_id="ci.output_json.run_result",
                    option="--output",
                    short="-o",
                    equals="json",
                    schema_key="run_result",
                    when="without --dry-check (normal run or --dry-run trace)",
                    exit_codes_with_json_on_stdout=(0, 1, 2),
                    positional_optional=("TARGET",),
                ),
            ],
            "config": [
                _stdout_json_route(
                    inv,
                    route_id="config.format_json.config_report",
                    option="--format",
                    short="-f",
                    equals="json",
                    schema_key="config_report",
                )
            ],
            "contract": [
                _stdout_json_route(
                    inv,
                    route_id="contract.format_json.workflow_contract_with_check",
                    option="--format",
                    short="-f",
                    equals="json",
                    schema_key="workflow_contract_check",
                    when="with --check SNAPSHOT (drift report; exit 1 when not ok)",
                    exit_codes_with_json_on_stdout=(0, 1),
                    positional_optional=("TARGET",),
                ),
                _stdout_json_route(
                    inv,
                    route_id="contract.format_json.workflow_contract_snapshot",
                    option="--format",
                    short="-f",
                    equals="json",
                    schema_key="workflow_contract",
                    when="without --check (live contract snapshot)",
                    positional_optional=("TARGET",),
                ),
            ],
            "diff": [
                _stdout_json_route(
                    inv,
                    route_id="diff.output_json.diff_report",
                    option="--output",
                    short="-o",
                    equals="json",
                    schema_key="diff_report",
                    positional_required=("RUN_A", "RUN_B"),
                )
            ],
            "doctor": [
                _stdout_json_route(
                    "doctor_preflight",
                    route_id="doctor.format_json.doctor_report",
                    option="--format",
                    short="-f",
                    equals="json",
                    schema_key="doctor_report",
                    exit_codes_with_json_on_stdout=(0, 1),
                )
            ],
            "init": [
                _stdout_json_route(
                    inv,
                    route_id="init.list_output_json.init_templates",
                    option="--output",
                    short="-o",
                    equals="json",
                    schema_key="init_templates",
                    when="with --list",
                ),
            ],
            "inspect": [
                _stdout_json_route(
                    inv,
                    route_id="inspect.output_json.inspect_report",
                    option="--output",
                    short="-o",
                    equals="json",
                    schema_key="inspect_report",
                    positional_required=("RUN_ID",),
                ),
                _stdout_json_route(
                    inv,
                    route_id="inspect.legacy_json_flag.inspect_report",
                    option="--json",
                    schema_key="inspect_report",
                    when="same payload as --output json",
                    boolean_flag=True,
                    positional_required=("RUN_ID",),
                ),
            ],
            "runs": [
                _stdout_json_route(
                    inv,
                    route_id="runs.output_json.runs_report",
                    option="--output",
                    short="-o",
                    equals="json",
                    schema_key="runs_report",
                )
            ],
            "run": [
                _stdout_json_route(
                    dry,
                    route_id="run.output_json.validate_report_with_dry_check",
                    option="--output",
                    short="-o",
                    equals="json",
                    schema_key="validate_report",
                    when="with --dry-check (graph/input validation only)",
                    exit_codes_with_json_on_stdout=(0, 1),
                    positional_optional=("TARGET",),
                ),
                _stdout_json_route(
                    runx,
                    route_id="run.output_json.run_result",
                    option="--output",
                    short="-o",
                    equals="json",
                    schema_key="run_result",
                    when="without --dry-check (normal run or --dry-run trace)",
                    exit_codes_with_json_on_stdout=(0, 1, 2),
                    positional_optional=("TARGET",),
                ),
            ],
            "seal": [
                _stdout_json_route(
                    "seal_manifest_write",
                    route_id="seal.output_json.seal",
                    option="--output",
                    short="-o",
                    equals="json",
                    schema_key="seal",
                    positional_required=("RUN_ID",),
                )
            ],
            "stats": [
                _stdout_json_route(
                    inv,
                    route_id="stats.output_json.stats_report",
                    option="--output",
                    short="-o",
                    equals="json",
                    schema_key="stats_report",
                )
            ],
            "try": [
                _stdout_json_route(
                    inv,
                    route_id="try.list_output_json.try_examples",
                    option="--output",
                    short="-o",
                    equals="json",
                    schema_key="try_examples",
                    when="with --list",
                ),
                _stdout_json_route(
                    inv,
                    route_id="try.print_snippet_output_json.try_print_snippet",
                    option="--output",
                    short="-o",
                    equals="json",
                    schema_key="try_print_snippet",
                    when="with --print-snippet KEY (no run; text stdout prints command only when --output text)",
                ),
                _stdout_json_route(
                    "try_copy_scaffold",
                    route_id="try.copy_to_output_json.try_copy",
                    option="--output",
                    short="-o",
                    equals="json",
                    schema_key="try_copy",
                    when="with --copy-to DIR",
                ),
                _stdout_json_route(
                    dry,
                    route_id="try.output_json.validate_report_with_dry_check",
                    option="--output",
                    short="-o",
                    equals="json",
                    schema_key="validate_report",
                    when="with --dry-check (invokes replayt run --dry-check)",
                    exit_codes_with_json_on_stdout=(0, 1),
                ),
                _stdout_json_route(
                    runx,
                    route_id="try.output_json.run_result",
                    option="--output",
                    short="-o",
                    equals="json",
                    schema_key="run_result",
                    when="example run path without --dry-check (invokes replayt run for the packaged target)",
                    exit_codes_with_json_on_stdout=(0, 1, 2),
                ),
            ],
            "validate": [
                _stdout_json_route(
                    inv,
                    route_id="validate.format_json.validate_report",
                    option="--format",
                    short="-f",
                    equals="json",
                    schema_key="validate_report",
                    exit_codes_with_json_on_stdout=(0, 1),
                    positional_optional=("TARGET",),
                )
            ],
            "verify-seal": [
                _stdout_json_route(
                    "verify_seal_compare",
                    route_id="verify_seal.output_json.verify_seal_report",
                    option="--output",
                    short="-o",
                    equals="json",
                    schema_key="verify_seal_report",
                    exit_codes_with_json_on_stdout=(0, 1),
                    positional_required=("RUN_ID",),
                )
            ],
            "version": [
                _stdout_json_route(
                    inv,
                    route_id="version.format_json.version_report",
                    option="--format",
                    short="-f",
                    equals="json",
                    schema_key="version_report",
                )
            ],
        },
    }
    sm = _CLI_JSON_STDOUT_ROUTE_SCHEMA_BY_KEY
    subcommands = contract["subcommands"]
    for routes in subcommands.values():
        for row in routes:
            sk = row["schema_key"]
            row["schema"] = sm[str(sk)]
    return contract


def build_log_mode_contract() -> dict[str, Any]:
    """Canonical ``LogMode`` string values for CLI, project config, and policy-hook env (version JSON)."""

    summaries: dict[str, str] = {
        "full": (
            "Persist full LLM request/response bodies in JSONL (subject to redact_keys); "
            "highest fidelity, largest logs."
        ),
        "redacted": (
            "Default-friendly mode: message bodies and previews are omitted or shortened while keeping structured "
            "outputs and metadata."
        ),
        "structured_only": (
            "Log llm_request / llm_response with timing, usage, and effective settings only (no message bodies); "
            "pair with ctx.llm.parse for structured_output without raw model text in the log."
        ),
    }
    modes = sorted(LogMode, key=lambda m: m.value)
    return {
        "schema": LOG_MODE_CONTRACT_SCHEMA,
        "payload": {
            "python_enum": "replayt.types.LogMode",
        },
        "modes": [
            {
                "value": m.value,
                "summary": summaries[m.value],
            }
            for m in modes
        ],
        "cli_flag": "--log-mode",
        "project_config_key": "log_mode",
        "policy_hook_env_var": "REPLAYT_LOG_MODE",
        "notes": [
            (
                "Only these three strings are accepted after CLI and config resolution; "
                "unknown values raise a clear error."
            ),
            (
                "policy_hook_env_var carries the effective mode into trusted hook subprocesses alongside "
                "REPLAYT_FORBID_LOG_MODE_FULL and REPLAYT_REDACT_KEYS_JSON (see policy_hook_env_catalog)."
            ),
            "Precedence for default redacted vs project log_mode is documented on project_setting_precedence_contract.",
        ],
        "project_setting_precedence_cross_reference": "log_mode",
    }


def build_jsonl_event_types_contract() -> dict[str, Any]:
    """Canonical JSONL envelope ``type`` strings replayt core emits (``replayt version --format json``)."""

    summaries: dict[str, str] = {
        "approval_applied": (
            "Emitted on resume when the runner continues from a different state than the pause point; "
            "pairs with a transition whose reason is approval_resolved."
        ),
        "approval_requested": (
            "Human gate requested from a step; payload may include on_approve / on_reject targets for resume pairing."
        ),
        "approval_resolved": (
            "Written by replayt resume or an approval bridge; records the decision for a prior approval_requested."
        ),
        "context_snapshot": (
            "Serializable RunContext.data snapshot taken when pausing for approval so resume can restore state."
        ),
        "llm_request": (
            "Outbound LLM call: effective settings, message fingerprints, and optional bodies when log_mode allows."
        ),
        "llm_response": (
            "Provider response metadata (and optional bodies in full mode) for the matching llm_request."
        ),
        "retry_scheduled": (
            "Step handler failed transiently; runner will retry up to the state's max_attempts."
        ),
        "run_completed": (
            "Terminal line: final_state and status completed or failed (failed runs also emit run_failed first)."
        ),
        "run_failed": (
            "Structured failure before the matching run_completed with status failed."
        ),
        "run_interrupted": (
            "Appended by the replayt run parent when --timeout expires: child subprocess was killed; "
            "not a runner-emitted terminal pair (see run_failed / run_completed)."
        ),
        "run_paused": (
            "Workflow paused (for example approval_required) with optional approval_id."
        ),
        "run_started": (
            "First line for a new run: workflow identity, inputs snapshot, tags, metadata, and runtime fingerprint."
        ),
        "state_entered": "Runner entered a workflow state before invoking its handler.",
        "state_exited": "Handler returned; records next_state (may be null when the run ends).",
        "step_error": (
            "Error classified to a specific state immediately before run_failed on exhausted retries or hard failures."
        ),
        "step_note": "Application breadcrumb from ctx.note (kind, optional summary and small data).",
        "structured_output": "Validated Pydantic model dump from ctx.llm.parse (or tagged complete_text).",
        "structured_output_failed": (
            "Parse or validation failure for structured output, with stage and optional validation_issue rows."
        ),
        "tool_call": "Registered tool invocation with name and arguments (optional vendor tool_call_id).",
        "tool_result": "Tool outcome or error for the matching tool_call (optional tool_call_id).",
        "transition": "Explicit graph edge from_state to to_state with optional reason string.",
    }
    types_sorted = sorted(summaries.keys())
    return {
        "schema": JSONL_EVENT_TYPES_CONTRACT_SCHEMA,
        "payload": {
            "envelope_type_field": "type",
            "payload_object_field": "payload",
            "run_log_schema_doc": "docs/RUN_LOG_SCHEMA.md",
        },
        "event_types": [{"value": t, "summary": summaries[t]} for t in types_sorted],
        "notes": [
            (
                "These type strings are what replayt core emits plus first-party CLI append paths (for example "
                "resume/approval and run_interrupted on replayt run --timeout) for the documented JSONL timeline; "
                "external writers (for example approval bridges) should use the same strings and payload shapes "
                "from docs/RUN_LOG_SCHEMA.md when appending lines."
            ),
            (
                "Use ctx.note (step_note) for small application breadcrumbs instead of inventing new envelope type "
                "strings; keep foreign or vendor-specific audit payloads in sidecar files when they are not part "
                "of the replay contract."
            ),
            "New first-class event kinds should be rare; ship them with a minor replayt bump and extend this contract.",
        ],
        "log_mode_contract_cross_reference": LOG_MODE_CONTRACT_SCHEMA,
    }


def build_run_result_status_contract() -> dict[str, Any]:
    """Canonical ``RunResult.status`` / ``replayt.run_result.v1`` status strings (version JSON)."""

    wf_cmds = ["ci", "resume", "run", "try"]
    return {
        "schema": RUN_RESULT_STATUS_CONTRACT_SCHEMA,
        "payload": {
            "schema_key": "run_result",
            "schema_id": RUN_RESULT_SCHEMA,
            "status_field": "status",
        },
        "statuses": [
            {
                "value": "completed",
                "typical_exit_code": 0,
                "workflow_subcommands": list(wf_cmds),
                "summary": "Workflow finished successfully without pause or unhandled failure.",
                "final_state": "Set to the last handler state when the run completes normally.",
                "error": "Usually null.",
            },
            {
                "value": "failed",
                "typical_exit_code": 1,
                "workflow_subcommands": list(wf_cmds),
                "summary": "Workflow failed, was interrupted, or a precondition or policy hook aborted the run.",
                "final_state": "Often the state where failure occurred; may be null when the run aborts early.",
                "error": "Human-oriented message when available.",
            },
            {
                "value": "paused",
                "typical_exit_code": 2,
                "workflow_subcommands": list(wf_cmds),
                "summary": "Paused for approval or similar; continue with replayt resume on the same run_id.",
                "final_state": "The state that requested pause.",
                "error": "Usually null.",
            },
        ],
        "notes": [
            "Only these three strings are produced for RunResult.status and replayt.run_result.v1 status.",
            "typical_exit_code matches cli_exit_codes.workflow_run.exit_codes for the listed subcommands.",
            (
                "List/filter helpers may surface an \"unknown\" terminal status when JSONL is incomplete; "
                "that label is not a RunResult.status value."
            ),
        ],
        "cli_exit_codes_cross_reference": "workflow_run",
    }


def build_cli_exit_codes_report() -> dict[str, Any]:
    """Machine-readable exit semantics for CI wrappers (``replayt version --format json``)."""

    return {
        "workflow_run": {
            "subcommands": ["ci", "resume", "run", "try"],
            "exit_codes": {
                "0": {
                    "run_status": "completed",
                    "summary": "Workflow finished successfully.",
                },
                "1": {
                    "run_status": "failed",
                    "summary": (
                        "Workflow failed, was interrupted, or a precondition or policy hook aborted "
                        "(see stderr)."
                    ),
                },
                "2": {
                    "run_status": "paused",
                    "summary": "Paused for approval; continue with replayt resume.",
                },
            },
        },
        "json_health_gates": {
            "doctor": {"healthy_exit": 0, "unhealthy_exit": 1},
            "validate": {"ok_exit": 0, "not_ok_exit": 1},
        },
        "note": (
            "Listing, inspection, export, and seal helpers exit 1 on user or lookup errors so exit 2 "
            "stays reserved for paused workflow runs."
        ),
        "typer_pre_dispatch_failures": {
            "typical_exit_code": 2,
            "summary": (
                "Typer usage failures (bad argv before the subcommand body runs) typically exit 2 with "
                "human-oriented stderr; stdout is often empty or non-JSON."
            ),
            "overlaps_workflow_pause_exit_code_on": ["ci", "resume", "run", "try"],
            "disambiguation": (
                "See cli_json_stdout_contract.typer_pre_dispatch_phase.exit_code_overlap in the same "
                "replayt version --format json payload: for JSON routes on run / ci / try, parse stdout "
                "for replayt.run_result.v1 with status paused versus a Typer parse failure; resume uses "
                "text stdout only (see disambiguation_for_resume_text_stdout there)."
            ),
        },
    }


def exit_for_run_result(result: RunResult) -> None:
    """Raise ``typer.Exit`` unless the run completed successfully."""

    code = exit_code_for_run_result(result)
    if code == 0:
        return
    raise typer.Exit(code=code)


def run_result_payload(wf: Workflow, result: RunResult) -> dict[str, Any]:
    return {
        "schema": RUN_RESULT_SCHEMA,
        "run_id": result.run_id,
        "workflow": f"{wf.name}@{wf.version}",
        "status": result.status,
        "final_state": result.final_state,
        "error": result.error,
    }
