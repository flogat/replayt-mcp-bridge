"""Command: config."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

import typer

import replayt
from replayt.cli.ci_artifacts import ci_artifacts_payload, resolve_ci_artifacts
from replayt.cli.config import (
    DEFAULT_LOG_DIR,
    export_hook_timeout_seconds,
    get_project_config,
    inputs_file_trust_audit_paths,
    min_replayt_version_report,
    preview_default_cli_target,
    preview_default_inputs_file,
    resolve_approval_actor_required_keys,
    resolve_approval_reason_required,
    resolve_forbid_log_mode_full,
    resolve_llm_settings,
    resolve_log_dir,
    resolve_log_mode_setting,
    resolve_redact_keys,
    resolve_sqlite_path,
    resolve_strict_mirror,
    resolve_timeout_setting,
    resume_hook_timeout_seconds,
    run_hook_timeout_seconds,
    seal_hook_timeout_seconds,
    verify_seal_hook_timeout_seconds,
)
from replayt.cli.path_readiness import ci_artifact_readiness_checks, readiness_checks
from replayt.cli.run_support import (
    export_hook_argv,
    policy_hook_trust_audit_paths_for_cfg,
    resume_hook_argv,
    run_hook_argv,
    seal_hook_argv,
    verify_seal_hook_argv,
)
from replayt.cli.targets import workflow_trust_audit_paths
from replayt.security import (
    dotenv_permission_trust_checks,
    dotenv_trust_candidate_paths,
    extraneous_llm_credential_env_names,
    inputs_file_permission_trust_checks,
    log_directory_permission_trust_checks,
    policy_hook_script_permission_trust_checks,
    trust_boundary_checks,
    workflow_entrypoint_permission_trust_checks,
)


def _config_report(
    *,
    log_dir: Path,
    log_subdir: str | None,
    sqlite: Path | None,
    log_mode: str,
    timeout: int | None,
) -> dict[str, object]:
    cfg, cfg_path, unknown_keys, shadowed_sources = get_project_config()
    resolved_log_dir = resolve_log_dir(log_dir, log_subdir)
    sqlite_path, sqlite_source = resolve_sqlite_path(sqlite, cfg, config_path=cfg_path)
    resolved_log_mode, log_mode_source = resolve_log_mode_setting(log_mode, cfg)
    forbid_lm_full, forbid_lm_full_source = resolve_forbid_log_mode_full(cfg)
    redact_keys, redact_keys_source = resolve_redact_keys(None, cfg)
    resolved_timeout, timeout_source = resolve_timeout_setting(timeout, cfg, in_child=False)
    strict_mirror = resolve_strict_mirror(cfg, sqlite=sqlite_path)
    required_actor_keys, required_actor_keys_source = resolve_approval_actor_required_keys(None, cfg)
    required_reason, required_reason_source = resolve_approval_reason_required(False, cfg)
    if "strict_mirror" in cfg:
        strict_mirror_source = "project_config:strict_mirror"
    elif sqlite_path is not None:
        strict_mirror_source = "derived:sqlite-present"
    else:
        strict_mirror_source = "derived:no-sqlite"
    llm_settings, llm_report = resolve_llm_settings(cfg)
    default_target, default_target_source = preview_default_cli_target(cfg)
    default_inputs_file, default_inputs_file_source = preview_default_inputs_file(cfg, config_path=cfg_path)
    ci_artifacts = resolve_ci_artifacts(
        explicit_junit_xml=None,
        explicit_summary_json=None,
        explicit_github_summary=False,
    )

    env_run_hook = os.environ.get("REPLAYT_RUN_HOOK", "").strip()
    run_hook = run_hook_argv(cfg)
    if env_run_hook:
        run_hook_source = "env:REPLAYT_RUN_HOOK"
    elif cfg.get("run_hook"):
        run_hook_source = "project_config:run_hook"
    else:
        run_hook_source = "unset"

    env_run_hook_timeout = os.environ.get("REPLAYT_RUN_HOOK_TIMEOUT", "").strip()
    if env_run_hook_timeout:
        run_hook_timeout_source = "env:REPLAYT_RUN_HOOK_TIMEOUT"
    elif cfg.get("run_hook_timeout") is not None:
        run_hook_timeout_source = "project_config:run_hook_timeout"
    else:
        run_hook_timeout_source = "default:120"

    env_hook = os.environ.get("REPLAYT_RESUME_HOOK", "").strip()
    resume_hook = resume_hook_argv(cfg)
    if env_hook:
        resume_hook_source = "env:REPLAYT_RESUME_HOOK"
    elif cfg.get("resume_hook"):
        resume_hook_source = "project_config:resume_hook"
    else:
        resume_hook_source = "unset"

    env_hook_timeout = os.environ.get("REPLAYT_RESUME_HOOK_TIMEOUT", "").strip()
    if env_hook_timeout:
        hook_timeout_source = "env:REPLAYT_RESUME_HOOK_TIMEOUT"
    elif cfg.get("resume_hook_timeout") is not None:
        hook_timeout_source = "project_config:resume_hook_timeout"
    else:
        hook_timeout_source = "default:120"

    env_export_hook = os.environ.get("REPLAYT_EXPORT_HOOK", "").strip()
    export_hook = export_hook_argv(cfg)
    if env_export_hook:
        export_hook_source = "env:REPLAYT_EXPORT_HOOK"
    elif cfg.get("export_hook"):
        export_hook_source = "project_config:export_hook"
    else:
        export_hook_source = "unset"

    env_export_hook_timeout = os.environ.get("REPLAYT_EXPORT_HOOK_TIMEOUT", "").strip()
    if env_export_hook_timeout:
        export_hook_timeout_source = "env:REPLAYT_EXPORT_HOOK_TIMEOUT"
    elif cfg.get("export_hook_timeout") is not None:
        export_hook_timeout_source = "project_config:export_hook_timeout"
    else:
        export_hook_timeout_source = "default:120"

    env_seal_hook = os.environ.get("REPLAYT_SEAL_HOOK", "").strip()
    seal_hook = seal_hook_argv(cfg)
    if env_seal_hook:
        seal_hook_source = "env:REPLAYT_SEAL_HOOK"
    elif cfg.get("seal_hook"):
        seal_hook_source = "project_config:seal_hook"
    else:
        seal_hook_source = "unset"

    env_seal_hook_timeout = os.environ.get("REPLAYT_SEAL_HOOK_TIMEOUT", "").strip()
    if env_seal_hook_timeout:
        seal_hook_timeout_source = "env:REPLAYT_SEAL_HOOK_TIMEOUT"
    elif cfg.get("seal_hook_timeout") is not None:
        seal_hook_timeout_source = "project_config:seal_hook_timeout"
    else:
        seal_hook_timeout_source = "default:120"

    env_verify_seal_hook = os.environ.get("REPLAYT_VERIFY_SEAL_HOOK", "").strip()
    verify_seal_hook = verify_seal_hook_argv(cfg)
    if env_verify_seal_hook:
        verify_seal_hook_source = "env:REPLAYT_VERIFY_SEAL_HOOK"
    elif cfg.get("verify_seal_hook"):
        verify_seal_hook_source = "project_config:verify_seal_hook"
    else:
        verify_seal_hook_source = "unset"

    env_verify_seal_hook_timeout = os.environ.get("REPLAYT_VERIFY_SEAL_HOOK_TIMEOUT", "").strip()
    if env_verify_seal_hook_timeout:
        verify_seal_hook_timeout_source = "env:REPLAYT_VERIFY_SEAL_HOOK_TIMEOUT"
    elif cfg.get("verify_seal_hook_timeout") is not None:
        verify_seal_hook_timeout_source = "project_config:verify_seal_hook_timeout"
    else:
        verify_seal_hook_timeout_source = "default:120"
    trust_base_url = llm_settings.base_url if llm_settings is not None else os.environ.get("OPENAI_BASE_URL")
    wf_trust_paths = workflow_trust_audit_paths(default_target) if default_target else []
    inputs_trust_paths = inputs_file_trust_audit_paths(default_inputs_file=default_inputs_file)
    trust_checks = (
        trust_boundary_checks(
            base_url=trust_base_url,
            log_mode=resolved_log_mode,
        )
        + log_directory_permission_trust_checks(resolved_log_dir)
        + dotenv_permission_trust_checks(
            dotenv_trust_candidate_paths(cwd=Path.cwd(), project_config_path=cfg_path)
        )
        + workflow_entrypoint_permission_trust_checks(wf_trust_paths)
        + inputs_file_permission_trust_checks(inputs_trust_paths)
        + policy_hook_script_permission_trust_checks(policy_hook_trust_audit_paths_for_cfg(cfg))
    )
    filesystem_checks = readiness_checks(log_dir=resolved_log_dir, sqlite=sqlite_path) + ci_artifact_readiness_checks(
        junit_xml=ci_artifacts.junit_xml,
        summary_json=ci_artifacts.summary_json,
        github_summary_requested=ci_artifacts.github_summary_requested,
        github_step_summary=ci_artifacts.github_step_summary,
    )
    min_ver = min_replayt_version_report(cfg, installed=replayt.__version__)

    return {
        "schema": "replayt.config_report.v1",
        "project_config": {
            "path": cfg_path,
            "keys": sorted(cfg.keys()),
            "unknown_keys": sorted(unknown_keys),
            "shadowed_sources": list(shadowed_sources),
            "min_replayt_version": min_ver["constraint"],
            "min_replayt_version_source": min_ver["constraint_source"],
            "min_replayt_version_satisfied": min_ver["satisfied"],
            "min_replayt_version_parse_error": min_ver["parse_error"],
            "replayt_version_installed": min_ver["installed"],
        },
        "paths": {
            "log_dir": str(resolved_log_dir),
            "log_dir_source": "cli:--log-dir" if log_dir != DEFAULT_LOG_DIR else "resolved_default",
            "log_subdir": log_subdir,
            "sqlite": str(sqlite_path) if sqlite_path is not None else None,
            "sqlite_source": sqlite_source,
        },
        "runtime_defaults": {
            "log_mode": resolved_log_mode,
            "log_mode_source": log_mode_source,
            "log_mode_full_forbidden": forbid_lm_full,
            "log_mode_full_forbidden_source": forbid_lm_full_source,
            "redact_keys": list(redact_keys),
            "redact_keys_source": redact_keys_source,
            "timeout_seconds": resolved_timeout,
            "timeout_source": timeout_source,
            "strict_mirror": strict_mirror,
            "strict_mirror_source": strict_mirror_source,
        },
        "run": {
            "default_target": default_target,
            "default_target_source": default_target_source,
            "default_inputs_file": default_inputs_file,
            "default_inputs_file_source": default_inputs_file_source,
            "hook_argv": run_hook,
            "hook_source": run_hook_source,
            "hook_timeout_seconds": run_hook_timeout_seconds(cfg),
            "hook_timeout_source": run_hook_timeout_source,
        },
        "resume": {
            "hook_argv": resume_hook,
            "hook_source": resume_hook_source,
            "hook_timeout_seconds": resume_hook_timeout_seconds(cfg),
            "hook_timeout_source": hook_timeout_source,
            "required_actor_keys": list(required_actor_keys),
            "required_actor_keys_source": required_actor_keys_source,
            "required_reason": required_reason,
            "required_reason_source": required_reason_source,
        },
        "export": {
            "hook_argv": export_hook,
            "hook_source": export_hook_source,
            "hook_timeout_seconds": export_hook_timeout_seconds(cfg),
            "hook_timeout_source": export_hook_timeout_source,
        },
        "seal": {
            "hook_argv": seal_hook,
            "hook_source": seal_hook_source,
            "hook_timeout_seconds": seal_hook_timeout_seconds(cfg),
            "hook_timeout_source": seal_hook_timeout_source,
        },
        "verify_seal": {
            "hook_argv": verify_seal_hook,
            "hook_source": verify_seal_hook_source,
            "hook_timeout_seconds": verify_seal_hook_timeout_seconds(cfg),
            "hook_timeout_source": verify_seal_hook_timeout_source,
        },
        "llm": {
            **llm_report,
            "timeout_seconds": llm_settings.timeout_seconds if llm_settings is not None else None,
            "max_response_bytes": llm_settings.max_response_bytes if llm_settings is not None else None,
            "max_schema_json_chars": llm_settings.max_schema_json_chars if llm_settings is not None else None,
        },
        "ci_artifacts": ci_artifacts_payload(ci_artifacts),
        "trust_boundary": {
            "checks": [
                {
                    "name": check.name,
                    "ok": check.ok,
                    "detail": check.detail,
                    "hint": check.hint,
                }
                for check in trust_checks
            ],
            "warnings": [check.detail for check in trust_checks if not check.ok],
        },
        "filesystem": {
            "checks": [
                {
                    "name": check.name,
                    "ok": check.ok,
                    "detail": check.detail,
                    "path": check.path,
                }
                for check in filesystem_checks
            ],
            "warnings": [check.detail for check in filesystem_checks if not check.ok],
        },
    }


def cmd_config(
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR, help="Directory for JSONL run logs."),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite mirror path."),
    log_mode: str = typer.Option("redacted", case_sensitive=False, help="redacted|full|structured_only"),
    timeout: int | None = typer.Option(None, "--timeout", help="Preview the effective run timeout."),
    output: Literal["text", "json"] = typer.Option("text", "--format", "-f", help="text or json."),
) -> None:
    """Show the effective replayt config after CLI args, project config, and env defaults are applied."""

    report = _config_report(
        log_dir=log_dir,
        log_subdir=log_subdir,
        sqlite=sqlite,
        log_mode=log_mode,
        timeout=timeout,
    )
    if output == "json":
        typer.echo(json.dumps(report, indent=2))
        return

    project = report["project_config"]
    paths = report["paths"]
    runtime = report["runtime_defaults"]
    run = report["run"]
    resume = report["resume"]
    export = report["export"]
    seal = report["seal"]
    verify_seal = report["verify_seal"]
    llm = report["llm"]
    ci_artifacts = report["ci_artifacts"]
    typer.echo(f"project_config={project['path'] or '(none)'}")
    uk = project.get("unknown_keys") or []
    if uk:
        typer.echo(f"project_config_unknown_keys={uk} (ignored; see docs/CONFIG.md#unknown-keys)")
    sh = project.get("shadowed_sources") or []
    if sh:
        typer.echo(
            "project_config_shadowed_sources="
            + ", ".join(str(p) for p in sh)
            + " (ignored; .replaytrc.toml takes precedence over pyproject.toml [tool.replayt] in the same directory)"
        )
    mv = project.get("min_replayt_version")
    if mv:
        typer.echo(
            f"min_replayt_version={mv} (satisfied={project['min_replayt_version_satisfied']}, "
            f"installed={project['replayt_version_installed']}; "
            f"{project['min_replayt_version_source']})"
        )
        pe = project.get("min_replayt_version_parse_error")
        if pe:
            typer.echo(f"min_replayt_version_parse_error={pe}")
    typer.echo(f"log_dir={paths['log_dir']} ({paths['log_dir_source']})")
    typer.echo(f"log_subdir={paths['log_subdir'] or '(none)'}")
    typer.echo(f"sqlite={paths['sqlite'] or '(none)'} ({paths['sqlite_source']})")
    typer.echo(f"log_mode={runtime['log_mode']} ({runtime['log_mode_source']})")
    typer.echo(
        f"log_mode_full_forbidden={runtime['log_mode_full_forbidden']} "
        f"({runtime['log_mode_full_forbidden_source']})"
    )
    typer.echo(f"redact_keys={runtime['redact_keys'] or '(none)'} ({runtime['redact_keys_source']})")
    typer.echo(f"timeout_seconds={runtime['timeout_seconds']} ({runtime['timeout_source']})")
    typer.echo(f"strict_mirror={runtime['strict_mirror']} ({runtime['strict_mirror_source']})")
    dt = run["default_target"]
    typer.echo(f"default_target={dt or '(none)'} ({run['default_target_source']})")
    dif = run["default_inputs_file"]
    typer.echo(f"default_inputs_file={dif or '(none)'} ({run['default_inputs_file_source']})")
    typer.echo(f"run_hook={run['hook_argv'] or '(none)'} ({run['hook_source']})")
    typer.echo(f"run_hook_timeout_seconds={run['hook_timeout_seconds']} ({run['hook_timeout_source']})")
    typer.echo(f"resume_hook={resume['hook_argv'] or '(none)'} ({resume['hook_source']})")
    typer.echo(
        f"resume_hook_timeout_seconds={resume['hook_timeout_seconds']} ({resume['hook_timeout_source']})"
    )
    typer.echo(
        f"approval_actor_required_keys={resume['required_actor_keys'] or '(none)'} "
        f"({resume['required_actor_keys_source']})"
    )
    typer.echo(f"approval_reason_required={resume['required_reason']} ({resume['required_reason_source']})")
    typer.echo(f"export_hook={export['hook_argv'] or '(none)'} ({export['hook_source']})")
    typer.echo(
        f"export_hook_timeout_seconds={export['hook_timeout_seconds']} "
        f"({export['hook_timeout_source']})"
    )
    typer.echo(f"seal_hook={seal['hook_argv'] or '(none)'} ({seal['hook_source']})")
    typer.echo(
        f"seal_hook_timeout_seconds={seal['hook_timeout_seconds']} ({seal['hook_timeout_source']})"
    )
    typer.echo(f"verify_seal_hook={verify_seal['hook_argv'] or '(none)'} ({verify_seal['hook_source']})")
    typer.echo(
        f"verify_seal_hook_timeout_seconds={verify_seal['hook_timeout_seconds']} "
        f"({verify_seal['hook_timeout_source']})"
    )
    typer.echo(f"provider={llm['provider']} ({llm['provider_source']})")
    typer.echo(f"base_url={llm.get('base_url') or '(invalid)'} ({llm['base_url_source']})")
    typer.echo(f"model={llm.get('model') or '(invalid)'} ({llm['model_source']})")
    typer.echo(f"openai_api_key={'set' if llm['api_key_present'] else 'missing'} ({llm['api_key_source']})")
    typer.echo(
        f"ci_junit_xml={ci_artifacts['junit_xml']['path'] or '(none)'} ({ci_artifacts['junit_xml']['source']})"
    )
    typer.echo(
        "ci_summary_json="
        f"{ci_artifacts['summary_json']['path'] or '(none)'} ({ci_artifacts['summary_json']['source']})"
    )
    typer.echo(
        "ci_github_summary_requested="
        f"{ci_artifacts['github_summary']['requested']} ({ci_artifacts['github_summary']['requested_source']})"
    )
    typer.echo(
        "ci_github_step_summary="
        f"{ci_artifacts['github_summary']['path'] or '(none)'} ({ci_artifacts['github_summary']['path_source']})"
    )
    extra_cred = extraneous_llm_credential_env_names()
    if extra_cred:
        typer.echo(
            "credential_env_note=These env vars are set but are not read by replayt's OpenAI-compat "
            f"client: {', '.join(extra_cred)} (presence-only audit; see --format json llm.credential_env)."
        )
    if llm.get("error"):
        typer.echo(f"provider_error={llm['error']}")
    for warning in report["trust_boundary"]["warnings"]:
        typer.echo(f"trust_boundary_warning={warning}")
    for check in report["filesystem"]["checks"]:
        typer.echo(f"{check['name']}={check['ok']} ({check['detail']})")


def register(app: typer.Typer) -> None:
    app.command("config")(cmd_config)
