"""Command: version."""

from __future__ import annotations

import json
import platform
import sys
from typing import Literal

import typer

import replayt
from replayt.cli.config import (
    CLI_RUN_DEFAULTS_CONTRACT_SCHEMA,
    PROJECT_SETTING_PRECEDENCE_CONTRACT_SCHEMA,
    SUPPORTED_CONFIG_KEYS,
    build_cli_run_defaults_contract,
    build_project_config_discovery_report,
    build_project_config_resolution_report,
    build_project_setting_precedence_contract,
)
from replayt.cli.distribution_metadata import DISTRIBUTION_METADATA_SCHEMA, build_distribution_metadata_report
from replayt.cli.path_readiness import build_operational_paths_report
from replayt.cli.run_support import (
    JSONL_EVENT_TYPES_CONTRACT_SCHEMA,
    LOG_MODE_CONTRACT_SCHEMA,
    RUN_RESULT_SCHEMA,
    RUN_RESULT_STATUS_CONTRACT_SCHEMA,
    build_cli_exit_codes_report,
    build_cli_json_stdout_contract,
    build_cli_stdio_contract,
    build_jsonl_event_types_contract,
    build_log_mode_contract,
    build_policy_hook_env_catalog,
    build_run_result_status_contract,
)
from replayt.cli.skill_loop_env import (
    SKILL_LOOP_ENV_CONTRACT_SCHEMA,
    build_skill_loop_env_contract,
)
from replayt.cli.skill_loop_placeholders import (
    SKILL_LOOP_PLACEHOLDER_CONTRACT_SCHEMA,
    build_skill_loop_placeholder_contract,
)

VERSION_REPORT_SCHEMA = "replayt.version_report.v1"

# Stable schema ids emitted by repo-local scripts under scripts/ (maintainer_checks loads these).
def _registered_cli_subcommands() -> list[str]:
    """Sorted top-level Typer command names (lazy import avoids cycles during CLI package import)."""

    from replayt.cli.main import app

    names: list[str] = []
    for info in app.registered_commands:
        n = getattr(info, "name", None)
        if n:
            names.append(str(n))
    return sorted(names)


MAINTAINER_SCRIPT_SCHEMAS: dict[str, str] = {
    "unreleased_changelog": "replayt.unreleased_changelog.v1",
    "changelog_gate_policy": "replayt.changelog_gate_policy.v1",
    "docs_index_report": "replayt.docs_index_report.v1",
    "version_consistency": "replayt.version_consistency.v1",
    "pyproject_pep621": "replayt.pyproject_pep621_report.v1",
    "example_catalog_contract": "replayt.example_catalog_contract.v1",
    "public_api_report": "replayt.public_api_report.v1",
    "maintainer_checks": "replayt.maintainer_checks.v1",
    "skill_invocation": "replayt.skill_invocation.v1",
    "skill_release_pipeline": "replayt.skill_release_pipeline.v1",
}


def build_version_report() -> dict[str, object]:
    vi = sys.version_info
    impl = sys.implementation
    impl_version = ".".join(str(part) for part in impl.version)
    cache_tag = getattr(impl, "cache_tag", None)
    return {
        "schema": VERSION_REPORT_SCHEMA,
        "replayt_version": replayt.__version__,
        "replayt_version_tuple": list(replayt.__version_tuple__),
        "python": {
            "version": f"{vi.major}.{vi.minor}.{vi.micro}",
            "major": vi.major,
            "minor": vi.minor,
            "micro": vi.micro,
            "releaselevel": vi.releaselevel,
            "serial": vi.serial,
            "implementation": {
                "name": impl.name,
                "version": impl_version,
                "cache_tag": cache_tag,
            },
        },
        "platform": sys.platform,
        "platform_machine": platform.machine(),
        "cli_subcommands": _registered_cli_subcommands(),
        "supported_project_config_keys": sorted(SUPPORTED_CONFIG_KEYS),
        "maintainer_script_schemas": dict(sorted(MAINTAINER_SCRIPT_SCHEMAS.items())),
        "policy_hook_env_catalog": build_policy_hook_env_catalog(),
        "cli_exit_codes": build_cli_exit_codes_report(),
        "run_result_status_contract": build_run_result_status_contract(),
        "log_mode_contract": build_log_mode_contract(),
        "jsonl_event_types_contract": build_jsonl_event_types_contract(),
        "cli_stdio_contract": build_cli_stdio_contract(),
        "cli_json_stdout_contract": build_cli_json_stdout_contract(),
        "project_config_discovery": build_project_config_discovery_report(),
        "project_config_resolution": build_project_config_resolution_report(),
        "cli_run_defaults_contract": build_cli_run_defaults_contract(),
        "project_setting_precedence_contract": build_project_setting_precedence_contract(),
        "operational_paths": build_operational_paths_report(),
        "distribution_metadata": build_distribution_metadata_report(),
        "skill_loop_env_contract": build_skill_loop_env_contract(),
        "skill_loop_placeholder_contract": build_skill_loop_placeholder_contract(),
        "cli_machine_readable_schemas": {
            "version_report": VERSION_REPORT_SCHEMA,
            "project_config_discovery": "replayt.project_config_discovery.v1",
            "project_config_resolution": "replayt.project_config_resolution.v1",
            "cli_run_defaults_contract": CLI_RUN_DEFAULTS_CONTRACT_SCHEMA,
            "project_setting_precedence_contract": PROJECT_SETTING_PRECEDENCE_CONTRACT_SCHEMA,
            "workflow_contract": "replayt.workflow_contract.v1",
            "workflow_contract_check": "replayt.workflow_contract_check.v1",
            "validate_report": "replayt.validate_report.v1",
            "doctor_report": "replayt.doctor_report.v1",
            "config_report": "replayt.config_report.v1",
            "ci_run_summary": "replayt.ci_run_summary.v1",
            "operational_paths": "replayt.operational_paths.v1",
            "distribution_metadata": DISTRIBUTION_METADATA_SCHEMA,
            "run_result": RUN_RESULT_SCHEMA,
            "run_result_status_contract": RUN_RESULT_STATUS_CONTRACT_SCHEMA,
            "log_mode_contract": LOG_MODE_CONTRACT_SCHEMA,
            "jsonl_event_types_contract": JSONL_EVENT_TYPES_CONTRACT_SCHEMA,
            "inspect_report": "replayt.inspect_report.v1",
            "runs_report": "replayt.runs_report.v1",
            "stats_report": "replayt.stats_report.v1",
            "diff_report": "replayt.diff_report.v1",
            "bundle_export": "replayt.bundle_export.v1",
            "export_bundle": "replayt.export_bundle.v1",
            "export_seal": "replayt.export_seal.v1",
            "seal": "replayt.seal.v1",
            "verify_seal_report": "replayt.verify_seal_report.v1",
            "try_examples": "replayt.try_examples.v1",
            "try_copy": "replayt.try_copy.v1",
            "try_print_snippet": "replayt.try_print_snippet.v1",
            "init_templates": "replayt.init_templates.v1",
            "skill_loop_env_contract": SKILL_LOOP_ENV_CONTRACT_SCHEMA,
            "skill_loop_placeholder_contract": SKILL_LOOP_PLACEHOLDER_CONTRACT_SCHEMA,
        },
    }


def cmd_version(
    output: Literal["text", "json"] = typer.Option(
        "text",
        "--format",
        "-f",
        help="text (default) or json (stable schema for CI / compatibility probes).",
    ),
) -> None:
    """Print replayt and Python runtime versions (machine-readable JSON optional)."""

    payload = build_version_report()
    if output == "json":
        typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo(f"replayt {payload['replayt_version']}")
    py = payload["python"]
    if isinstance(py, dict):
        typer.echo(f"python {py['version']}")
    typer.echo(f"platform {payload['platform']}")


def register(app: typer.Typer) -> None:
    app.command("version")(cmd_version)
