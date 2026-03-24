"""Optional CI outputs (JUnit XML, GitHub Actions step summary, machine-readable summary)."""

from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from replayt.cli.run_support import exit_code_for_run_result
from replayt.runner import RunResult
from replayt.workflow import Workflow

# Env vars commonly set by hosted CI vendors. Only *presence* is recorded on
# ``replayt.ci_run_summary.v1`` (never values), so summaries stay correlation-safe.
CI_MARKER_ENV_NAMES: tuple[str, ...] = (
    "BITBUCKET_PIPELINE_UUID",
    "BUILDKITE",
    "CI",
    "CIRCLECI",
    "CODEBUILD_BUILD_ID",
    "DRONE",
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "JENKINS_URL",
    "TEAMCITY_VERSION",
    "TF_BUILD",
    "TRAVIS",
)


def _ci_marker_env_presence() -> dict[str, bool]:
    return {name: bool(os.environ.get(name, "").strip()) for name in CI_MARKER_ENV_NAMES}


def _host_clock_utc_offset_minutes() -> int | None:
    """Local wall clock's offset from UTC in whole minutes, or ``None`` if unknown."""

    try:
        off = datetime.now().astimezone().utcoffset()
    except (OSError, OverflowError, ValueError):
        return None
    if off is None:
        return None
    secs = int(round(off.total_seconds()))
    return secs // 60


def _ulimit_nofile_pair() -> tuple[int | None, int | None]:
    """Best-effort RLIMIT_NOFILE soft/hard caps (POSIX only)."""

    if os.name != "posix":
        return None, None
    try:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (AttributeError, OSError, ValueError):
        return None, None
    return int(soft), int(hard)


@dataclass(frozen=True)
class ResolvedCIArtifacts:
    junit_xml: Path | None
    junit_xml_source: str
    summary_json: Path | None
    summary_json_source: str
    github_summary_requested: bool
    github_summary_requested_source: str
    github_step_summary: Path | None
    github_step_summary_source: str


def ci_run_summary_runtime_fields() -> dict[str, Any]:
    """Stable host/interpreter stamps for machine-readable CI summaries."""

    try:
        import replayt as _rt

        replayt_version = getattr(_rt, "__version__", "unknown")
    except ImportError:
        replayt_version = "unknown"
    vi = sys.version_info
    fs_enc = sys.getfilesystemencoding()
    soft, hard = _ulimit_nofile_pair()
    impl = sys.implementation
    cache_tag = getattr(impl, "cache_tag", None)
    return {
        "replayt_version": replayt_version,
        "python_version": f"{vi.major}.{vi.minor}.{vi.micro}",
        "python_implementation": platform.python_implementation(),
        "python_cache_tag": cache_tag,
        "python_utf8_mode": int(sys.flags.utf8_mode),
        "python_executable": sys.executable,
        "platform": sys.platform,
        "machine": platform.machine(),
        "os_cpu_count": os.cpu_count(),
        "filesystem_encoding": fs_enc if fs_enc is not None else "",
        "stdout_encoding": getattr(sys.stdout, "encoding", None),
        "ulimit_nofile_soft": soft,
        "ulimit_nofile_hard": hard,
        "ci_marker_env": _ci_marker_env_presence(),
        "host_clock_utc_offset_minutes": _host_clock_utc_offset_minutes(),
    }


def parse_ci_metadata_from_env() -> dict[str, Any] | None:
    """Parse ``REPLAYT_CI_METADATA_JSON`` when set; must be a JSON object.

    Used to enrich ``replayt.ci_run_summary.v1`` with pipeline correlation fields
    (build id, commit, job URL) supplied by the caller's CI shell.
    """

    raw = os.environ.get("REPLAYT_CI_METADATA_JSON", "").strip()
    if not raw:
        return None
    try:
        val = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"REPLAYT_CI_METADATA_JSON is not valid JSON: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(val, dict):
        raise ValueError(
            "REPLAYT_CI_METADATA_JSON must be a JSON object (mapping), not an array or scalar."
        )
    return val


def _xml_escape_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xml_escape_attr(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def write_junit_xml(path: Path, *, wf: Workflow, result: RunResult) -> None:
    """Write a minimal JUnit file for CI systems (one testcase per invocation)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    cls_name = _xml_escape_attr(f"{wf.name}@{wf.version}")
    msg = f"status={result.status} run_id={result.run_id}"
    if result.error:
        msg += f" error={result.error}"
    msg_esc = _xml_escape_text(msg)
    msg_attr = _xml_escape_attr(msg)
    if result.status == "completed":
        failures = errors = skipped = 0
        case_inner = ""
    elif result.status == "paused":
        failures = errors = 0
        skipped = 1
        case_inner = f'<skipped message="{msg_attr}"/>'
    else:
        failures = 1
        errors = skipped = 0
        case_inner = f'<failure message="run failed">{msg_esc}</failure>'
    doc = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<testsuites>\n"
        f'  <testsuite name="replayt" tests="1" failures="{failures}" errors="{errors}" skipped="{skipped}">\n'
        f'    <testcase name="workflow_run" classname="{cls_name}">{case_inner}</testcase>\n'
        "  </testsuite>\n"
        "</testsuites>\n"
    )
    path.write_text(doc, encoding="utf-8")


def _step_summary_path_and_source() -> tuple[Path | None, str]:
    """Resolve the markdown step-summary sink and which env var supplied it.

    GitHub Actions sets ``GITHUB_STEP_SUMMARY``; for other CI systems set ``REPLAYT_STEP_SUMMARY``
    to a writable file path. When both are set, ``GITHUB_STEP_SUMMARY`` wins.
    """

    gh = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if gh:
        return Path(gh), "env:GITHUB_STEP_SUMMARY"
    rt = os.environ.get("REPLAYT_STEP_SUMMARY", "").strip()
    if rt:
        return Path(rt), "env:REPLAYT_STEP_SUMMARY"
    return None, "unset"


def step_summary_env_snapshot() -> dict[str, str | None]:
    """Machine-readable step-summary path for ``replayt version --format json``."""

    path, src = _step_summary_path_and_source()
    if path is None:
        return {"path": None, "path_source": src}
    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = str(path)
    return {"path": resolved, "path_source": src}


def _resolve_step_summary_path() -> Path | None:
    """Where to append markdown when ``--github-summary`` / ``REPLAYT_GITHUB_SUMMARY`` is on."""

    path, _src = _step_summary_path_and_source()
    return path


def append_github_step_summary(
    wf: Workflow,
    result: RunResult,
    *,
    duration_ms: int | None = None,
) -> None:
    summary_path = _resolve_step_summary_path()
    if summary_path is None:
        return
    lines = [
        "## replayt ci",
        "",
        f"- **Workflow:** `{wf.name}@{wf.version}`",
        f"- **run_id:** `{result.run_id}`",
        f"- **status:** `{result.status}`",
    ]
    if duration_ms is not None:
        lines.append(f"- **duration_ms:** `{duration_ms}`")
    if result.error:
        lines.append(f"- **error:** `{result.error}`")
    lines.append("")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_summary_json(
    path: Path,
    *,
    wf: Workflow,
    result: RunResult,
    target: str,
    log_dir: Path,
    sqlite: Path | None = None,
    dry_run: bool = False,
    duration_ms: int | None = None,
    ci_metadata: dict[str, Any] | None = None,
) -> None:
    """Write one machine-readable run summary artifact for CI wrappers."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema": "replayt.ci_run_summary.v1",
        "workflow": f"{wf.name}@{wf.version}",
        "workflow_name": wf.name,
        "workflow_version": wf.version,
        "run_id": result.run_id,
        "status": result.status,
        "final_state": result.final_state,
        "error": result.error,
        "exit_code": exit_code_for_run_result(result),
        "target": target,
        "cwd": str(Path.cwd().resolve()),
        "log_dir": str(log_dir.resolve()),
        "dry_run": dry_run,
        **ci_run_summary_runtime_fields(),
    }
    if sqlite is not None:
        payload["sqlite"] = str(sqlite.resolve())
    else:
        payload["sqlite"] = None
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    if ci_metadata is not None:
        payload["ci_metadata"] = ci_metadata
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def resolve_ci_junit_path(explicit: Path | None) -> Path | None:
    """Explicit ``replayt ci --junit-xml`` wins; else ``REPLAYT_JUNIT_XML`` for ad-hoc scripts."""

    if explicit is not None:
        return explicit
    env_j = os.environ.get("REPLAYT_JUNIT_XML", "").strip()
    return Path(env_j) if env_j else None


def resolve_ci_summary_json_path(explicit: Path | None) -> Path | None:
    """Explicit ``replayt ci --summary-json`` wins; else ``REPLAYT_SUMMARY_JSON`` for scripts."""

    if explicit is not None:
        return explicit
    env_summary = os.environ.get("REPLAYT_SUMMARY_JSON", "").strip()
    return Path(env_summary) if env_summary else None


def should_write_github_step_summary(explicit: bool) -> bool:
    return explicit or os.environ.get("REPLAYT_GITHUB_SUMMARY") == "1"


def resolve_ci_artifacts(
    *,
    explicit_junit_xml: Path | None,
    explicit_summary_json: Path | None,
    explicit_github_summary: bool,
) -> ResolvedCIArtifacts:
    env_junit = os.environ.get("REPLAYT_JUNIT_XML", "").strip()
    env_summary = os.environ.get("REPLAYT_SUMMARY_JSON", "").strip()
    env_github_toggle = os.environ.get("REPLAYT_GITHUB_SUMMARY", "").strip()
    step_path, step_source = _step_summary_path_and_source()

    return ResolvedCIArtifacts(
        junit_xml=resolve_ci_junit_path(explicit_junit_xml),
        junit_xml_source=(
            "cli:--junit-xml" if explicit_junit_xml is not None else "env:REPLAYT_JUNIT_XML" if env_junit else "unset"
        ),
        summary_json=resolve_ci_summary_json_path(explicit_summary_json),
        summary_json_source=(
            "cli:--summary-json"
            if explicit_summary_json is not None
            else "env:REPLAYT_SUMMARY_JSON"
            if env_summary
            else "unset"
        ),
        github_summary_requested=should_write_github_step_summary(explicit_github_summary),
        github_summary_requested_source=(
            "cli:--github-summary"
            if explicit_github_summary
            else "env:REPLAYT_GITHUB_SUMMARY"
            if env_github_toggle == "1"
            else "unset"
        ),
        github_step_summary=step_path,
        github_step_summary_source=step_source,
    )


def ci_artifacts_payload(artifacts: ResolvedCIArtifacts) -> dict[str, Any]:
    def _path_value(path: Path | None) -> str | None:
        return str(path.resolve()) if path is not None else None

    return {
        "junit_xml": {
            "path": _path_value(artifacts.junit_xml),
            "source": artifacts.junit_xml_source,
        },
        "summary_json": {
            "path": _path_value(artifacts.summary_json),
            "source": artifacts.summary_json_source,
        },
        "github_summary": {
            "requested": artifacts.github_summary_requested,
            "requested_source": artifacts.github_summary_requested_source,
            "path": _path_value(artifacts.github_step_summary),
            "path_source": artifacts.github_step_summary_source,
        },
    }


def write_ci_artifacts(
    wf: Workflow,
    result: RunResult,
    *,
    junit_path: Path | None,
    summary_json_path: Path | None,
    github_summary: bool,
    target: str,
    log_dir: Path,
    sqlite: Path | None = None,
    dry_run: bool = False,
    duration_ms: int | None = None,
    ci_metadata: dict[str, Any] | None = None,
) -> None:
    if junit_path is not None:
        write_junit_xml(junit_path, wf=wf, result=result)
    if summary_json_path is not None:
        write_summary_json(
            summary_json_path,
            wf=wf,
            result=result,
            target=target,
            log_dir=log_dir,
            sqlite=sqlite,
            dry_run=dry_run,
            duration_ms=duration_ms,
            ci_metadata=ci_metadata,
        )
    if github_summary:
        append_github_step_summary(wf, result, duration_ms=duration_ms)
