"""Best-effort filesystem readiness checks for CLI defaults and doctor output."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PathReadinessCheck:
    name: str
    ok: bool
    detail: str
    path: str | None = None


def _writable_dir(path: Path) -> bool:
    return os.access(path, os.W_OK | os.X_OK)


def _nearest_existing_parent(path: Path) -> Path | None:
    candidate = path
    while True:
        if candidate.exists():
            return candidate
        if candidate.parent == candidate:
            return None
        candidate = candidate.parent


def _directory_check(path: Path, *, name: str, label: str) -> PathReadinessCheck:
    if path.exists():
        if not path.is_dir():
            return PathReadinessCheck(
                name=name,
                ok=False,
                detail=f"{label} exists but is not a directory",
                path=str(path),
            )
        if not _writable_dir(path):
            return PathReadinessCheck(
                name=name,
                ok=False,
                detail=f"{label} exists but is not writable by the current process",
                path=str(path),
            )
        return PathReadinessCheck(name=name, ok=True, detail=f"{label} exists and is writable", path=str(path))

    parent = _nearest_existing_parent(path.parent if path.parent != path else path)
    if parent is None:
        return PathReadinessCheck(
            name=name,
            ok=False,
            detail=f"{label} has no existing parent directory",
            path=str(path),
        )
    if not parent.is_dir():
        return PathReadinessCheck(
            name=name,
            ok=False,
            detail=f"{label} cannot be created because parent {parent} is not a directory",
            path=str(path),
        )
    if not _writable_dir(parent):
        return PathReadinessCheck(
            name=name,
            ok=False,
            detail=f"{label} does not exist and parent {parent} is not writable",
            path=str(path),
        )
    return PathReadinessCheck(
        name=name,
        ok=True,
        detail=f"{label} does not exist yet; replayt can create it under {parent}",
        path=str(path),
    )


def _file_check(path: Path, *, name: str, label: str) -> PathReadinessCheck:
    if path.exists():
        if path.is_dir():
            return PathReadinessCheck(name=name, ok=False, detail=f"{label} exists but is a directory", path=str(path))
        if not os.access(path, os.W_OK):
            return PathReadinessCheck(
                name=name,
                ok=False,
                detail=f"{label} exists but is not writable by the current process",
                path=str(path),
            )
        return PathReadinessCheck(name=name, ok=True, detail=f"{label} exists and is writable", path=str(path))

    parent = _nearest_existing_parent(path.parent if path.parent != path else path)
    if parent is None:
        return PathReadinessCheck(
            name=name,
            ok=False,
            detail=f"{label} has no existing parent directory",
            path=str(path),
        )
    if not parent.is_dir():
        return PathReadinessCheck(
            name=name,
            ok=False,
            detail=f"{label} cannot be created because parent {parent} is not a directory",
            path=str(path),
        )
    if not _writable_dir(parent):
        return PathReadinessCheck(
            name=name,
            ok=False,
            detail=f"{label} does not exist and parent {parent} is not writable",
            path=str(path),
        )
    return PathReadinessCheck(
        name=name,
        ok=True,
        detail=f"{label} does not exist yet; replayt can create it under {parent}",
        path=str(path),
    )


def readiness_checks(*, log_dir: Path, sqlite: Path | None) -> list[PathReadinessCheck]:
    checks = [_directory_check(log_dir, name="log_dir_ready", label="log_dir")]
    if sqlite is None:
        checks.append(
            PathReadinessCheck(
                name="sqlite_ready",
                ok=True,
                detail="sqlite mirror not configured",
                path=None,
            )
        )
    else:
        checks.append(_file_check(sqlite, name="sqlite_ready", label="sqlite path"))
    return checks


def ci_artifact_readiness_checks(
    *,
    junit_xml: Path | None,
    summary_json: Path | None,
    github_summary_requested: bool,
    github_step_summary: Path | None,
) -> list[PathReadinessCheck]:
    checks: list[PathReadinessCheck] = []
    if junit_xml is None:
        checks.append(
            PathReadinessCheck(
                name="ci_junit_xml_ready",
                ok=True,
                detail="JUnit XML artifact not configured",
                path=None,
            )
        )
    else:
        checks.append(_file_check(junit_xml, name="ci_junit_xml_ready", label="JUnit XML artifact"))

    if summary_json is None:
        checks.append(
            PathReadinessCheck(
                name="ci_summary_json_ready",
                ok=True,
                detail="CI summary JSON artifact not configured",
                path=None,
            )
        )
    else:
        checks.append(_file_check(summary_json, name="ci_summary_json_ready", label="CI summary JSON artifact"))

    if not github_summary_requested:
        checks.append(
            PathReadinessCheck(
                name="ci_github_summary_ready",
                ok=True,
                detail="GitHub step summary not requested",
                path=None,
            )
        )
    elif github_step_summary is None:
        checks.append(
            PathReadinessCheck(
                name="ci_github_summary_ready",
                ok=False,
                detail=(
                    "GitHub step summary requested but neither GITHUB_STEP_SUMMARY nor "
                    "REPLAYT_STEP_SUMMARY is set"
                ),
                path=None,
            )
        )
    else:
        checks.append(
            _file_check(
                github_step_summary,
                name="ci_github_summary_ready",
                label="GitHub step summary path",
            )
        )
    return checks


def build_operational_paths_report() -> dict[str, object]:
    """Cwd-resolved paths for CI wrappers (``replayt version --format json``)."""

    from replayt.cli.ci_artifacts import (
        resolve_ci_artifacts,
        resolve_ci_junit_path,
        resolve_ci_summary_json_path,
        step_summary_env_snapshot,
    )
    from replayt.cli.config import DEFAULT_LOG_DIR, resolve_log_dir

    cwd = Path.cwd().resolve()
    log_dir = resolve_log_dir(DEFAULT_LOG_DIR).resolve()
    junit = resolve_ci_junit_path(None)
    summary_json = resolve_ci_summary_json_path(None)
    artifacts = resolve_ci_artifacts(
        explicit_junit_xml=None,
        explicit_summary_json=None,
        explicit_github_summary=False,
    )
    readiness = ci_artifact_readiness_checks(
        junit_xml=artifacts.junit_xml,
        summary_json=artifacts.summary_json,
        github_summary_requested=artifacts.github_summary_requested,
        github_step_summary=artifacts.github_step_summary,
    )
    readiness_payload = [
        {"name": c.name, "ok": c.ok, "detail": c.detail, "path": c.path} for c in readiness
    ]
    return {
        "schema": "replayt.operational_paths.v1",
        "cwd": str(cwd),
        "effective_log_dir": str(log_dir),
        "step_summary": step_summary_env_snapshot(),
        "ci_artifact_paths": {
            "junit_xml": str(junit.resolve()) if junit is not None else None,
            "summary_json": str(summary_json.resolve()) if summary_json is not None else None,
        },
        "ci_artifact_readiness": readiness_payload,
        "ci_artifact_readiness_ok": all(c.ok for c in readiness),
    }
