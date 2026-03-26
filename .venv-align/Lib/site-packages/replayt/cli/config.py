"""Project config discovery ([tool.replayt], .replaytrc.toml) and log path helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import typer

from replayt.cli.validation import parse_json_object_cli_ref, parse_json_object_option
from replayt.llm import LLMSettings
from replayt.security import (
    egress_trust_env_presence,
    llm_credential_env_presence,
    normalize_name_list,
    sanitize_base_url_for_output,
)
from replayt.types import LogMode

SUPPORTED_CONFIG_KEYS = frozenset(
    {
        "log_dir",
        "log_mode",
        "redact_keys",
        "sqlite",
        "provider",
        "model",
        "timeout",
        "strict_mirror",
        "target",
        "run_hook",
        "run_hook_timeout",
        "resume_hook",
        "resume_hook_timeout",
        "export_hook",
        "export_hook_timeout",
        "seal_hook",
        "seal_hook_timeout",
        "verify_seal_hook",
        "verify_seal_hook_timeout",
        "approval_actor_required_keys",
        "min_replayt_version",
        "inputs_file",
        "approval_reason_required",
        "forbid_log_mode_full",
        "policy_hook_context_json",
    }
)

_PROJECT_CONFIG: dict[str, Any] | None = None
_PROJECT_CONFIG_PATH: str | None = None
_PROJECT_CONFIG_UNKNOWN_KEYS: frozenset[str] | None = None
_PROJECT_CONFIG_SHADOWED_SOURCES: tuple[str, ...] | None = None
_PROJECT_CONFIG_WALK: list[dict[str, Any]] | None = None
_PROJECT_CONFIG_CWD: str | None = None

PROJECT_CONFIG_DISCOVERY_SCHEMA = "replayt.project_config_discovery.v1"
PROJECT_CONFIG_RESOLUTION_SCHEMA = "replayt.project_config_resolution.v1"


def build_project_config_discovery_report() -> dict[str, object]:
    """Stable, cwd-independent description of how project config files are discovered (for CI / wrappers)."""

    return {
        "schema": PROJECT_CONFIG_DISCOVERY_SCHEMA,
        "walk": "cwd_then_parent_directories",
        "per_directory_checks": [
            {
                "id": "replaytrc_toml",
                "relative_path": ".replaytrc.toml",
                "shape": "toml_root_table",
                "stops_walk_when_file_exists": True,
            },
            {
                "id": "pyproject_tool_replayt",
                "relative_path": "pyproject.toml",
                "shape": "toml_nested_table",
                "toml_path": ["tool", "replayt"],
                "stops_walk_when_table_present": True,
            },
        ],
        "same_directory_precedence": "replaytrc_before_pyproject",
        "shadowed_sources_note": (
            "When both files exist in one directory, only .replaytrc.toml is read; pyproject.toml [tool.replayt] is "
            "ignored. replayt config --format json lists shadowed_sources; replayt doctor warns when non-empty."
        ),
    }

DEFAULT_LOG_DIR = Path(".replayt/runs")

REPLAYT_TARGET_ENV = "REPLAYT_TARGET"
REPLAYT_INPUTS_FILE_ENV = "REPLAYT_INPUTS_FILE"
REPLAYT_FORBID_LOG_MODE_FULL_ENV = "REPLAYT_FORBID_LOG_MODE_FULL"
REPLAYT_POLICY_HOOK_CONTEXT_JSON_ENV = "REPLAYT_POLICY_HOOK_CONTEXT_JSON"


def resolve_policy_hook_context_json(cli_raw: str | None, *, cfg: dict[str, Any]) -> str | None:
    """Return canonical JSON (sorted keys) for ``REPLAYT_POLICY_HOOK_CONTEXT_JSON``, or ``None`` when unset.

    Precedence: ``--policy-hook-context-json`` > ``REPLAYT_POLICY_HOOK_CONTEXT_JSON`` >
    ``[tool.replayt]`` / ``.replaytrc.toml`` ``policy_hook_context_json``. Not written to JSONL;
    only forwarded to trusted policy-hook subprocesses.
    """

    if cli_raw is not None:
        s = str(cli_raw).strip()
        if not s:
            raise typer.BadParameter(
                "--policy-hook-context-json cannot be empty; omit the flag to use env / project config."
            )
        obj = parse_json_object_cli_ref(s, label="--policy-hook-context-json")
        return json.dumps(obj, sort_keys=True)
    env_val = os.environ.get(REPLAYT_POLICY_HOOK_CONTEXT_JSON_ENV, "").strip()
    if env_val:
        obj = parse_json_object_option(env_val, label=REPLAYT_POLICY_HOOK_CONTEXT_JSON_ENV)
        return json.dumps(obj, sort_keys=True)
    cfg_val = cfg.get("policy_hook_context_json")
    if isinstance(cfg_val, str) and cfg_val.strip():
        obj = parse_json_object_option(cfg_val.strip(), label="policy_hook_context_json")
        return json.dumps(obj, sort_keys=True)
    return None


def resolve_cli_target(explicit: str | None, *, cfg: dict[str, Any]) -> str:
    """Resolve workflow target: CLI arg, then env, then project config.

    Used by ``replayt run`` / ``replayt ci`` and by ``replayt validate`` / ``graph`` / ``contract``
    when the positional ``TARGET`` is omitted.
    """

    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    env_t = os.environ.get(REPLAYT_TARGET_ENV, "").strip()
    if env_t:
        return env_t
    raw = cfg.get("target")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    raise typer.BadParameter(
        "Missing workflow target: pass TARGET (MODULE:VAR or workflow file), "
        f"set {REPLAYT_TARGET_ENV}, or set `target = \"...\"` in [tool.replayt] / .replaytrc.toml "
        "(see docs/CONFIG.md).\n"
        "Examples:\n"
        "  replayt run replayt_examples.e01_hello_world:wf --input customer_name=Sam\n"
        "  replayt try --list\n"
        "  replayt init\n"
        "Docs: docs/QUICKSTART.md and src/replayt_examples/README.md."
    )


def preview_default_cli_target(cfg: dict[str, Any]) -> tuple[str | None, str]:
    """Target used when TARGET is omitted on ``run`` / ``ci``; does not raise."""

    env_t = os.environ.get(REPLAYT_TARGET_ENV, "").strip()
    if env_t:
        return env_t, f"env:{REPLAYT_TARGET_ENV}"
    raw = cfg.get("target")
    if isinstance(raw, str) and raw.strip():
        return raw.strip(), "project_config:target"
    return None, "unset"


def preview_default_inputs_file(cfg: dict[str, Any], *, config_path: str | None) -> tuple[str | None, str]:
    """Default inputs JSON file for ``run`` / ``ci`` / ``validate`` / ``doctor --target`` when CLI omits inputs."""

    env_raw = os.environ.get(REPLAYT_INPUTS_FILE_ENV, "").strip()
    if env_raw:
        if env_raw == "-":
            return "-", f"env:{REPLAYT_INPUTS_FILE_ENV} (stdin)"
        return str(Path(env_raw).expanduser().resolve()), f"env:{REPLAYT_INPUTS_FILE_ENV}"
    cfg_raw = cfg.get("inputs_file")
    if isinstance(cfg_raw, str) and cfg_raw.strip():
        p = resolve_project_path(cfg_raw.strip(), config_path=config_path)
        return str(p.resolve()), "project_config:inputs_file"
    return None, "unset"


def inputs_file_trust_audit_paths(
    *,
    default_inputs_file: str | None,
    explicit_inputs_file: Path | None = None,
) -> list[Path]:
    """Paths to existing inputs JSON files for POSIX permission audits (resolved; mode bits only in checks)."""

    paths: list[Path] = []
    seen: set[str] = set()
    for raw in (default_inputs_file, explicit_inputs_file):
        if raw is None:
            continue
        label = str(raw).strip()
        if not label or label == "-":
            continue
        try:
            p = Path(label).expanduser().resolve()
        except OSError:
            continue
        if not p.is_file():
            continue
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        paths.append(p)
    return paths


def resolve_run_inputs_json(
    inputs_json: str | None,
    inputs_file: Path | None,
    *,
    cfg: dict[str, Any],
    config_path: str | None,
    input_value: list[str] | None = None,
) -> tuple[str | None, str]:
    """Resolve inputs for ``run`` / ``ci`` / ``validate`` / ``doctor --target``.

    Precedence: ``--inputs-json`` / ``--inputs-file``, then ``REPLAYT_INPUTS_FILE``, then
    ``[tool.replayt] inputs_file`` / ``.replaytrc.toml`` (relative paths from the config file).
    Repeatable ``--input`` values merge on top of whichever base object resolves.
    """

    from replayt.cli.validation import inputs_json_from_options

    if inputs_json is not None or inputs_file is not None:
        resolved = inputs_json_from_options(
            inputs_json, inputs_file, input_value, inputs_file_origin="cli"
        )
        if inputs_file is not None:
            src = "cli:--inputs-file (stdin)" if inputs_file == Path("-") else "cli:--inputs-file"
        elif inputs_json is not None:
            sj = inputs_json.strip()
            if sj.startswith("@"):
                ref = sj[1:].strip()
                src = "cli:--inputs-json @- (stdin)" if ref == "-" else "cli:--inputs-json @path"
            else:
                src = "cli:--inputs-json"
        else:
            src = "cli"
        return resolved, src

    env_raw = os.environ.get(REPLAYT_INPUTS_FILE_ENV, "").strip()
    if env_raw:
        if env_raw == "-":
            resolved = inputs_json_from_options(None, Path("-"), input_value)
            return resolved, f"env:{REPLAYT_INPUTS_FILE_ENV} (stdin)"
        p = Path(env_raw).expanduser()
        resolved = inputs_json_from_options(
            None, p, input_value, inputs_file_origin="env"
        )
        return resolved, f"env:{REPLAYT_INPUTS_FILE_ENV}"

    cfg_raw = cfg.get("inputs_file")
    if isinstance(cfg_raw, str) and cfg_raw.strip():
        p = resolve_project_path(cfg_raw.strip(), config_path=config_path)
        resolved = inputs_json_from_options(
            None, p, input_value, inputs_file_origin="project"
        )
        return resolved, "project_config:inputs_file"

    if input_value:
        resolved = inputs_json_from_options(None, None, input_value)
        return resolved, "cli:--input"

    return None, "unset"


CLI_RUN_DEFAULTS_CONTRACT_SCHEMA = "replayt.cli_run_defaults_contract.v1"


def build_cli_run_defaults_contract() -> dict[str, object]:
    """Cwd-independent precedence rules for optional TARGET and run inputs (for CI, wrappers, and docs parity)."""

    return {
        "schema": CLI_RUN_DEFAULTS_CONTRACT_SCHEMA,
        "workflow_target": {
            "optional_on_commands": ["ci", "contract", "graph", "run", "validate"],
            "precedence": [
                {
                    "order": 1,
                    "id": "cli_positional_target",
                    "description": (
                        "Non-empty TARGET argument on replayt run / replayt ci / replayt validate / "
                        "replayt graph / replayt contract "
                        "(MODULE:VAR or a trusted workflow .py / .yaml / .yml path)."
                    ),
                },
                {
                    "order": 2,
                    "id": "env_REPLAYT_TARGET",
                    "env": REPLAYT_TARGET_ENV,
                    "description": (
                        "Non-empty REPLAYT_TARGET when TARGET is omitted on run, ci, validate, graph, or contract."
                    ),
                },
                {
                    "order": 3,
                    "id": "project_config_target",
                    "config_key": "target",
                    "description": (
                        "Non-empty target from the resolved project config "
                        "([tool.replayt] or .replaytrc.toml; see project_config_discovery / project_config_resolution)."
                    ),
                },
            ],
            "missing_behavior": (
                "Typer raises BadParameter: pass TARGET, set REPLAYT_TARGET, or set target in project config "
                "(see docs/CONFIG.md)."
            ),
            "required_target_elsewhere_note": (
                "replayt resume still requires TARGET on argv. replayt doctor --target uses only the flag value. "
                "Commands that take a run id (inspect, replay, export-run, bundle-export, seal, verify-seal, report, "
                "…) do not use REPLAYT_TARGET or project_config target."
            ),
        },
        "run_inputs": {
            "commands_using_resolve_run_inputs_json": ["ci", "doctor", "run", "validate"],
            "doctor_note": (
                "doctor calls resolve_run_inputs_json only when --target is set (inputs preflight for that target)."
            ),
            "precedence": [
                {
                    "order": 1,
                    "id": "cli_inputs_json_or_file",
                    "description": (
                        "When --inputs-json and/or --inputs-file is provided, that path wins; repeatable --input "
                        "values merge on top of the parsed JSON object (@path and @- stdin rules match "
                        "replayt validate)."
                    ),
                },
                {
                    "order": 2,
                    "id": "env_REPLAYT_INPUTS_FILE",
                    "env": REPLAYT_INPUTS_FILE_ENV,
                    "description": (
                        "When CLI inputs are omitted, non-empty REPLAYT_INPUTS_FILE (path or - for stdin); --input "
                        "still merges on top."
                    ),
                },
                {
                    "order": 3,
                    "id": "project_config_inputs_file",
                    "config_key": "inputs_file",
                    "description": (
                        "Path relative to the resolved config file when env and CLI omit inputs; --input merges on top."
                    ),
                },
                {
                    "order": 4,
                    "id": "cli_input_only",
                    "description": (
                        "When no base JSON object is resolved but --input is present, inputs are built only from "
                        "--input (source label cli:--input in replayt config --format json)."
                    ),
                },
                {
                    "order": 5,
                    "id": "unset",
                    "description": "Otherwise inputs are unset until try/cmd_run supplies defaults.",
                },
            ],
        },
    }


PROJECT_SETTING_PRECEDENCE_CONTRACT_SCHEMA = "replayt.project_setting_precedence_contract.v1"


def build_project_setting_precedence_contract() -> dict[str, object]:
    """Cwd-independent precedence for CLI / env / project merges beyond TARGET and default inputs.

    Pairs with :func:`build_cli_run_defaults_contract` for a full platform picture without duplicating
    workflow target or ``resolve_run_inputs_json`` ordering.
    """

    policy_hooks = [
        {
            "config_key": "export_hook",
            "env_argv": "REPLAYT_EXPORT_HOOK",
            "config_key_timeout": "export_hook_timeout",
            "env_timeout": "REPLAYT_EXPORT_HOOK_TIMEOUT",
        },
        {
            "config_key": "resume_hook",
            "env_argv": "REPLAYT_RESUME_HOOK",
            "config_key_timeout": "resume_hook_timeout",
            "env_timeout": "REPLAYT_RESUME_HOOK_TIMEOUT",
        },
        {
            "config_key": "run_hook",
            "env_argv": "REPLAYT_RUN_HOOK",
            "config_key_timeout": "run_hook_timeout",
            "env_timeout": "REPLAYT_RUN_HOOK_TIMEOUT",
        },
        {
            "config_key": "seal_hook",
            "env_argv": "REPLAYT_SEAL_HOOK",
            "config_key_timeout": "seal_hook_timeout",
            "env_timeout": "REPLAYT_SEAL_HOOK_TIMEOUT",
        },
        {
            "config_key": "verify_seal_hook",
            "env_argv": "REPLAYT_VERIFY_SEAL_HOOK",
            "config_key_timeout": "verify_seal_hook_timeout",
            "env_timeout": "REPLAYT_VERIFY_SEAL_HOOK_TIMEOUT",
        },
    ]

    return {
        "schema": PROJECT_SETTING_PRECEDENCE_CONTRACT_SCHEMA,
        "extends_cli_run_defaults_contract": CLI_RUN_DEFAULTS_CONTRACT_SCHEMA,
        "extends_note": (
            "Optional TARGET on replayt run / ci / validate / graph / contract and resolve_run_inputs_json ordering "
            "(including doctor --target) are specified only in cli_run_defaults_contract; this object covers other "
            "merged settings."
        ),
        "settings": [
            {
                "id": "approval_actor_required_keys",
                "precedence": [
                    {
                        "order": 1,
                        "id": "cli_require_actor_key",
                        "description": (
                            "When --require-actor-key is passed one or more times, those names win; project "
                            "approval_actor_required_keys is ignored."
                        ),
                    },
                    {
                        "order": 2,
                        "id": "project_config_approval_actor_required_keys",
                        "config_key": "approval_actor_required_keys",
                        "description": "Otherwise normalized list from project config when present.",
                    },
                    {
                        "order": 3,
                        "id": "unset_empty_tuple",
                        "description": "Otherwise empty (no required actor keys).",
                    },
                ],
            },
            {
                "id": "approval_reason_required",
                "precedence": [
                    {
                        "order": 1,
                        "id": "cli_require_reason",
                        "description": "When --require-reason is passed, policy is on regardless of project config.",
                    },
                    {
                        "order": 2,
                        "id": "project_config_approval_reason_required",
                        "config_key": "approval_reason_required",
                        "description": "Otherwise boolean from project config when the key is present.",
                    },
                    {
                        "order": 3,
                        "id": "unset_false",
                        "description": "Otherwise false.",
                    },
                ],
            },
            {
                "id": "forbid_log_mode_full",
                "precedence": [
                    {
                        "order": 1,
                        "id": "env_REPLAYT_FORBID_LOG_MODE_FULL",
                        "env": REPLAYT_FORBID_LOG_MODE_FULL_ENV,
                        "description": (
                            "When set in the environment, any non-empty value except 0/false/no/off forces the "
                            "policy on; those falsy strings force it off even when project config sets "
                            "forbid_log_mode_full."
                        ),
                    },
                    {
                        "order": 2,
                        "id": "project_config_forbid_log_mode_full",
                        "config_key": "forbid_log_mode_full",
                        "description": "Otherwise true when forbid_log_mode_full is truthy in project config.",
                    },
                    {
                        "order": 3,
                        "id": "unset_false",
                        "description": "Otherwise false.",
                    },
                ],
            },
            {
                "id": "llm_client_defaults",
                "precedence": [
                    {
                        "order": 1,
                        "id": "env_REPLAYT_PROVIDER",
                        "env": "REPLAYT_PROVIDER",
                        "description": "Provider preset name when non-empty; else project provider; else ollama.",
                    },
                    {
                        "order": 2,
                        "id": "env_REPLAYT_MODEL",
                        "env": "REPLAYT_MODEL",
                        "description": "Model id when non-empty; else project model; else provider default.",
                    },
                    {
                        "order": 3,
                        "id": "env_OPENAI_BASE_URL",
                        "env": "OPENAI_BASE_URL",
                        "description": "Base URL when non-empty; else built-in preset for the resolved provider.",
                    },
                    {
                        "order": 4,
                        "id": "env_OPENAI_API_KEY",
                        "env": "OPENAI_API_KEY",
                        "description": "API key for the default OpenAI-compat client (env only; not read from TOML).",
                    },
                ],
            },
            {
                "id": "log_directory",
                "applies_when": (
                    "CLI --log-dir equals the built-in default (.replayt/runs). A non-default --log-dir is used "
                    "as-is with no project or env fallback."
                ),
                "precedence": [
                    {
                        "order": 1,
                        "id": "project_config_log_dir",
                        "config_key": "log_dir",
                        "description": (
                            "When log_dir is set in resolved project config, that path (relative to the config file) "
                            "replaces the default root."
                        ),
                    },
                    {
                        "order": 2,
                        "id": "env_REPLAYT_LOG_DIR",
                        "env": "REPLAYT_LOG_DIR",
                        "description": "When project log_dir is unset, non-empty REPLAYT_LOG_DIR replaces the default.",
                    },
                    {
                        "order": 3,
                        "id": "builtin_default",
                        "description": "Otherwise .replayt/runs under cwd (DEFAULT_LOG_DIR).",
                    },
                ],
            },
            {
                "id": "log_mode",
                "precedence": [
                    {
                        "order": 1,
                        "id": "project_config_when_cli_redacted_string",
                        "config_key": "log_mode",
                        "description": (
                            "When the effective --log-mode value is the string redacted and project log_mode is set, "
                            "project log_mode wins (Typer cannot distinguish omitted --log-mode from an explicit "
                            "redacted pass)."
                        ),
                    },
                    {
                        "order": 2,
                        "id": "cli_log_mode_other_values",
                        "description": "When the effective --log-mode value is not redacted, that CLI value wins.",
                    },
                    {
                        "order": 3,
                        "id": "default_redacted",
                        "description": "Otherwise redacted with source default:redacted.",
                    },
                ],
            },
            {
                "id": "min_replayt_version",
                "precedence": [
                    {
                        "order": 1,
                        "id": "project_config_only",
                        "config_key": "min_replayt_version",
                        "description": (
                            "Only [tool.replayt] / .replaytrc.toml; no CLI or env override. Enforced on mutating "
                            "CLI entrypoints via enforce_min_replayt_version_cli."
                        ),
                    }
                ],
            },
            {
                "id": "policy_hook_context_json",
                "precedence": [
                    {
                        "order": 1,
                        "id": "cli_policy_hook_context_json",
                        "description": (
                            "Non-empty --policy-hook-context-json on run / ci / resume / export-run / "
                            "bundle-export / seal / verify-seal (object or @path); canonical sorted JSON."
                        ),
                    },
                    {
                        "order": 2,
                        "id": "env_REPLAYT_POLICY_HOOK_CONTEXT_JSON",
                        "env": REPLAYT_POLICY_HOOK_CONTEXT_JSON_ENV,
                        "description": "When CLI omits the flag, non-empty env string is parsed as JSON object.",
                    },
                    {
                        "order": 3,
                        "id": "project_config_policy_hook_context_json",
                        "config_key": "policy_hook_context_json",
                        "description": "When env is unset, non-empty project policy_hook_context_json string.",
                    },
                    {
                        "order": 4,
                        "id": "unset_none",
                        "description": "Otherwise not forwarded to hooks.",
                    },
                ],
            },
            {
                "id": "redact_keys",
                "precedence": [
                    {
                        "order": 1,
                        "id": "cli_redact_key",
                        "description": "When --redact-key is passed one or more times, those names win.",
                    },
                    {
                        "order": 2,
                        "id": "project_config_redact_keys",
                        "config_key": "redact_keys",
                        "description": "Otherwise normalized list from project config when present.",
                    },
                    {
                        "order": 3,
                        "id": "unset_empty_tuple",
                        "description": "Otherwise empty.",
                    },
                ],
            },
            {
                "id": "sqlite_mirror_path",
                "precedence": [
                    {
                        "order": 1,
                        "id": "cli_sqlite",
                        "description": "When --sqlite is passed, that path wins.",
                    },
                    {
                        "order": 2,
                        "id": "project_config_sqlite",
                        "config_key": "sqlite",
                        "description": "Otherwise sqlite path from project config when set (relative to config file).",
                    },
                    {
                        "order": 3,
                        "id": "unset_none",
                        "description": "Otherwise no SQLite mirror.",
                    },
                ],
            },
            {
                "id": "strict_mirror_policy",
                "precedence": [
                    {
                        "order": 1,
                        "id": "project_config_strict_mirror",
                        "config_key": "strict_mirror",
                        "description": "When strict_mirror is present in project config, its boolean value wins.",
                    },
                    {
                        "order": 2,
                        "id": "implicit_strict_when_sqlite",
                        "description": (
                            "When strict_mirror is omitted, strict mirroring is true if a SQLite path resolved "
                            "from CLI or project config; false when no mirror path."
                        ),
                    },
                ],
            },
            {
                "id": "subprocess_timeout_seconds",
                "commands": ["ci", "run"],
                "precedence": [
                    {
                        "order": 1,
                        "id": "child_process_disabled",
                        "description": (
                            "When replayt run --timeout isolates the workflow in a child, timeout is unset in the "
                            "parent path."
                        ),
                    },
                    {
                        "order": 2,
                        "id": "cli_timeout",
                        "description": "When --timeout is set on the parent CLI, that integer wins.",
                    },
                    {
                        "order": 3,
                        "id": "project_config_timeout",
                        "config_key": "timeout",
                        "description": "Otherwise project timeout when set.",
                    },
                    {
                        "order": 4,
                        "id": "unset_none",
                        "description": "Otherwise unset (provider default HTTP behavior).",
                    },
                ],
            },
            {
                "id": "trusted_policy_hook_argv",
                "merge_policy": "replace_not_concatenate",
                "precedence": [
                    {
                        "order": 1,
                        "id": "env_hook_string",
                        "description": (
                            "Non-empty env hook string wins; argv is shlex.split with posix=True on Unix and "
                            "posix=False on Windows. There is no argv merge with TOML."
                        ),
                    },
                    {
                        "order": 2,
                        "id": "project_config_hook",
                        "description": (
                            "Otherwise list of strings or one shell string from project config for that hook key."
                        ),
                    },
                    {
                        "order": 3,
                        "id": "unset_none",
                        "description": "Otherwise hook is disabled.",
                    },
                ],
                "hooks": policy_hooks,
            },
            {
                "id": "trusted_policy_hook_timeouts",
                "precedence": [
                    {
                        "order": 1,
                        "id": "env_hook_timeout",
                        "description": (
                            "Non-empty env timeout overrides project; parsed as float; value <= 0 means unlimited."
                        ),
                    },
                    {
                        "order": 2,
                        "id": "project_config_hook_timeout",
                        "description": "Otherwise project *_hook_timeout when set (same <= 0 unlimited rule).",
                    },
                    {
                        "order": 3,
                        "id": "default_120_seconds",
                        "description": "Otherwise 120 seconds.",
                    },
                ],
                "hooks": policy_hooks,
            },
        ],
    }


def _split_supported_section(section: dict[str, Any]) -> tuple[dict[str, Any], frozenset[str]]:
    """Keep only supported keys; return unknown top-level keys (e.g. TOML typos) for diagnostics."""

    filtered: dict[str, Any] = {}
    unknown: set[str] = set()
    for key, value in section.items():
        if not isinstance(key, str):
            continue
        if key in SUPPORTED_CONFIG_KEYS:
            filtered[key] = value
        else:
            unknown.add(key)
    return filtered, frozenset(unknown)


def resolve_project_path(raw_path: str | Path, *, config_path: str | None) -> Path:
    """Resolve project-configured paths relative to the config file that declared them."""

    path = Path(str(raw_path))
    if path.is_absolute() or config_path is None:
        return path
    return Path(config_path).resolve().parent / path


def _shadowed_pyproject_paths_when_replaytrc_wins(directory: Path, tomllib_mod: Any) -> tuple[str, ...]:
    """Return pyproject paths skipped because ``.replaytrc.toml`` won in this directory."""

    pyproject = directory / "pyproject.toml"
    if not pyproject.is_file():
        return ()
    try:
        with open(pyproject, "rb") as f:
            pdata = tomllib_mod.load(f)
    except (OSError, UnicodeDecodeError, ValueError, TypeError):
        return ()
    section = (pdata.get("tool") or {}).get("replayt")
    if isinstance(section, dict):
        return (str(pyproject.resolve()),)
    return ()


def _read_pyproject_tool_replayt_section(pyproject: Path, tomllib_mod: Any) -> dict[str, Any] | None:
    """Return the ``[tool.replayt]`` table dict when present and mapping-shaped; else ``None``."""

    try:
        with open(pyproject, "rb") as f:
            data = tomllib_mod.load(f)
    except (OSError, UnicodeDecodeError, ValueError, TypeError):
        return None
    section = (data.get("tool") or {}).get("replayt")
    return section if isinstance(section, dict) else None


def load_project_config() -> tuple[dict[str, Any], str | None, frozenset[str], tuple[str, ...], list[dict[str, Any]]]:
    """Walk up from cwd looking for ``pyproject.toml`` (``[tool.replayt]``) or ``.replaytrc.toml``."""

    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found,no-redef]
        except ImportError:
            return {}, None, frozenset(), (), []

    cur = Path.cwd().resolve()
    walk: list[dict[str, Any]] = []
    for directory in (cur, *cur.parents):
        rc = directory / ".replaytrc.toml"
        pyproject = directory / "pyproject.toml"
        rc_exists = rc.is_file()
        pj_exists = pyproject.is_file()
        pj_section = _read_pyproject_tool_replayt_section(pyproject, tomllib) if pj_exists else None
        pj_has = pj_section is not None

        if rc_exists:
            walk.append(
                {
                    "directory": str(directory),
                    "replaytrc_toml": True,
                    "pyproject_toml": pj_exists,
                    "pyproject_has_tool_replayt": pj_has,
                    "stopped_here": True,
                }
            )
            with open(rc, "rb") as f:
                data = tomllib.load(f)
            if not isinstance(data, dict):
                shadowed = _shadowed_pyproject_paths_when_replaytrc_wins(directory, tomllib)
                return {}, str(rc.resolve()), frozenset(), shadowed, walk
            filtered, unknown = _split_supported_section(data)
            shadowed = _shadowed_pyproject_paths_when_replaytrc_wins(directory, tomllib)
            return filtered, str(rc.resolve()), unknown, shadowed, walk

        if pj_has:
            assert pj_section is not None
            walk.append(
                {
                    "directory": str(directory),
                    "replaytrc_toml": False,
                    "pyproject_toml": True,
                    "pyproject_has_tool_replayt": True,
                    "stopped_here": True,
                }
            )
            filtered, unknown = _split_supported_section(pj_section)
            return filtered, str(pyproject.resolve()), unknown, (), walk

        walk.append(
            {
                "directory": str(directory),
                "replaytrc_toml": rc_exists,
                "pyproject_toml": pj_exists,
                "pyproject_has_tool_replayt": pj_has,
                "stopped_here": False,
            }
        )

    return {}, None, frozenset(), (), walk


def get_project_config() -> tuple[dict[str, Any], str | None, frozenset[str], tuple[str, ...]]:
    global _PROJECT_CONFIG  # noqa: PLW0603
    global _PROJECT_CONFIG_PATH  # noqa: PLW0603
    global _PROJECT_CONFIG_UNKNOWN_KEYS  # noqa: PLW0603
    global _PROJECT_CONFIG_SHADOWED_SOURCES  # noqa: PLW0603
    global _PROJECT_CONFIG_WALK  # noqa: PLW0603
    global _PROJECT_CONFIG_CWD  # noqa: PLW0603
    cwd = str(Path.cwd().resolve())
    if _PROJECT_CONFIG is None or _PROJECT_CONFIG_CWD != cwd:
        (
            _PROJECT_CONFIG,
            _PROJECT_CONFIG_PATH,
            _PROJECT_CONFIG_UNKNOWN_KEYS,
            _PROJECT_CONFIG_SHADOWED_SOURCES,
            _PROJECT_CONFIG_WALK,
        ) = load_project_config()
        _PROJECT_CONFIG_CWD = cwd
    return _PROJECT_CONFIG, _PROJECT_CONFIG_PATH, _PROJECT_CONFIG_UNKNOWN_KEYS, _PROJECT_CONFIG_SHADOWED_SOURCES


def build_project_config_resolution_report() -> dict[str, object]:
    """Cwd-scoped project config discovery trace for ``replayt version --format json`` / CI assertions."""

    _cfg, path, unknown, shadowed = get_project_config()
    walk = list(_PROJECT_CONFIG_WALK or [])
    cwd = str(Path.cwd().resolve())
    winner: dict[str, str] | None
    if path is None:
        winner = None
    else:
        name = Path(path).name
        if name == ".replaytrc.toml":
            kind = "replaytrc"
        elif name == "pyproject.toml":
            kind = "pyproject"
        else:
            kind = "unknown"
        winner = {"path": path, "kind": kind}
    return {
        "schema": PROJECT_CONFIG_RESOLUTION_SCHEMA,
        "cwd": cwd,
        "winner": winner,
        "unknown_keys": sorted(unknown),
        "shadowed_sources": list(shadowed),
        "walk": walk,
    }


def sanitize_log_subdir(raw: str) -> str:
    s = raw.strip()
    if not s:
        raise typer.BadParameter("log_subdir must be non-empty")
    if os.path.sep in s or (os.altsep and os.altsep in s):
        raise typer.BadParameter("log_subdir must be a single path segment (no slashes)")
    if s.startswith(".") or s in (".", ".."):
        raise typer.BadParameter("log_subdir cannot start with '.'")
    return s


def resolve_log_dir(cli_log_dir: Path, log_subdir: str | None = None) -> Path:
    """Apply ``[tool.replayt]`` / ``REPLAYT_LOG_DIR`` defaults and optional tenant subdir."""

    cfg, cfg_path, _unknown, _shadowed = get_project_config()
    base = cli_log_dir
    if cli_log_dir == DEFAULT_LOG_DIR:
        if cfg.get("log_dir"):
            base = resolve_project_path(cfg["log_dir"], config_path=cfg_path)
        else:
            env_ld = os.environ.get("REPLAYT_LOG_DIR")
            if env_ld:
                base = Path(env_ld)
    if log_subdir is not None:
        base = base / sanitize_log_subdir(log_subdir)
    return base


def resolve_sqlite_path(
    cli_sqlite: Path | None,
    cfg: dict[str, Any],
    *,
    config_path: str | None,
) -> tuple[Path | None, str]:
    if cli_sqlite is not None:
        return cli_sqlite, "cli:--sqlite"
    if cfg.get("sqlite"):
        return resolve_project_path(cfg["sqlite"], config_path=config_path), "project_config:sqlite"
    return None, "unset"


def resolve_log_mode_setting(cli_log_mode: str, cfg: dict[str, Any]) -> tuple[str, str]:
    if cli_log_mode == "redacted" and cfg.get("log_mode"):
        return str(cfg["log_mode"]), "project_config:log_mode"
    return cli_log_mode, "cli:--log-mode" if cli_log_mode != "redacted" else "default:redacted"


def resolve_forbid_log_mode_full(cfg: dict[str, Any]) -> tuple[bool, str]:
    """Whether ``log_mode=full`` must be rejected on run/ci/resume (env overrides project config)."""

    raw = os.environ.get(REPLAYT_FORBID_LOG_MODE_FULL_ENV)
    if raw is not None:
        key = str(raw).strip().lower()
        if key in {"0", "false", "no", "off"}:
            return False, f"env:{REPLAYT_FORBID_LOG_MODE_FULL_ENV}"
        if key:
            return True, f"env:{REPLAYT_FORBID_LOG_MODE_FULL_ENV}"
    if bool(cfg.get("forbid_log_mode_full")):
        return True, "project_config:forbid_log_mode_full"
    return False, "unset"


def enforce_forbid_log_mode_full_cli(*, forbid: bool, forbid_source: str, resolved_log_mode: str) -> None:
    """Fail CLI entrypoints when policy forbids ``LogMode.full``."""

    if not forbid:
        return
    lm = parse_log_mode(resolved_log_mode)
    if lm == LogMode.full:
        raise typer.BadParameter(
            "log_mode=full is forbidden by "
            f"{forbid_source}. "
            "Use --log-mode redacted or structured_only, clear "
            f"{REPLAYT_FORBID_LOG_MODE_FULL_ENV}, or remove forbid_log_mode_full from project config "
            "(see docs/CONFIG.md)."
        )


def resolve_redact_keys(cli_redact_keys: list[str] | None, cfg: dict[str, Any]) -> tuple[tuple[str, ...], str]:
    if cli_redact_keys:
        return normalize_name_list(cli_redact_keys), "cli:--redact-key"
    cfg_value = cfg.get("redact_keys")
    if isinstance(cfg_value, list):
        return normalize_name_list([str(item) for item in cfg_value]), "project_config:redact_keys"
    return (), "unset"


def resolve_approval_actor_required_keys(
    cli_required_keys: list[str] | None,
    cfg: dict[str, Any],
) -> tuple[tuple[str, ...], str]:
    if cli_required_keys:
        return normalize_name_list(cli_required_keys), "cli:--require-actor-key"
    cfg_value = cfg.get("approval_actor_required_keys")
    if isinstance(cfg_value, list):
        return normalize_name_list([str(item) for item in cfg_value]), "project_config:approval_actor_required_keys"
    return (), "unset"


def resolve_approval_reason_required(cli_require_reason: bool, cfg: dict[str, Any]) -> tuple[bool, str]:
    if cli_require_reason:
        return True, "cli:--require-reason"
    if "approval_reason_required" in cfg:
        return bool(cfg.get("approval_reason_required")), "project_config:approval_reason_required"
    return False, "unset"


def resolve_timeout_setting(
    timeout: int | None,
    cfg: dict[str, Any],
    *,
    in_child: bool = False,
) -> tuple[int | None, str]:
    if in_child:
        return None, "child_process:disabled"
    if timeout is not None:
        return timeout, "cli:--timeout"
    if cfg.get("timeout"):
        return int(cfg["timeout"]), "project_config:timeout"
    return None, "unset"


def resolve_strict_mirror(cfg: dict[str, Any], *, sqlite: Path | None) -> bool:
    """Mirror write policy: explicit ``strict_mirror`` in config, else strict when ``--sqlite`` is used."""

    if "strict_mirror" in cfg:
        return bool(cfg["strict_mirror"])
    return sqlite is not None


def resolve_llm_settings(cfg: dict[str, Any]) -> tuple[LLMSettings | None, dict[str, Any]]:
    env_provider = os.environ.get("REPLAYT_PROVIDER", "").strip()
    env_model = os.environ.get("REPLAYT_MODEL", "").strip()
    env_base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    api_key = os.environ.get("OPENAI_API_KEY")

    cfg_provider = str(cfg.get("provider", "")).strip() if cfg.get("provider") is not None else ""
    cfg_model = str(cfg.get("model", "")).strip() if cfg.get("model") is not None else ""

    provider = env_provider or cfg_provider or None
    model = env_model or cfg_model or None
    provider_source = (
        "env:REPLAYT_PROVIDER"
        if env_provider
        else "project_config:provider"
        if cfg_provider
        else "default:ollama"
    )
    model_source = (
        "env:REPLAYT_MODEL"
        if env_model
        else "project_config:model"
        if cfg_model
        else f"provider_default:{provider or 'ollama'}"
    )
    base_url_source = "env:OPENAI_BASE_URL" if env_base_url else f"provider_preset:{provider or 'ollama'}"
    api_key_source = "env:OPENAI_API_KEY" if api_key else "unset"

    report: dict[str, Any] = {
        "provider": provider or "ollama",
        "provider_source": provider_source,
        "model_source": model_source,
        "base_url_source": base_url_source,
        "api_key_present": bool(api_key),
        "api_key_source": api_key_source,
        "credential_env": llm_credential_env_presence(),
        "egress_trust_env": egress_trust_env_presence(),
    }
    try:
        settings = LLMSettings.from_sources(
            provider=provider,
            base_url=env_base_url or None,
            model=model,
            api_key=api_key,
        )
    except ValueError as exc:
        report["error"] = str(exc)
        if env_base_url:
            report["base_url"] = sanitize_base_url_for_output(env_base_url)
        if model:
            report["model"] = model
        return None, report

    report["base_url"] = sanitize_base_url_for_output(settings.base_url)
    report["model"] = settings.model
    return settings, report


def _hook_timeout_seconds(cfg: dict[str, Any], *, env_var: str, config_key: str) -> float | None:
    env_raw = os.environ.get(env_var, "").strip()
    if env_raw:
        v = float(env_raw)
        return None if v <= 0 else v
    cfg_val = cfg.get(config_key)
    if cfg_val is not None:
        v = float(cfg_val)
        return None if v <= 0 else v
    return 120.0


def run_hook_timeout_seconds(cfg: dict[str, Any]) -> float | None:
    """Wall-clock limit for the ``run_hook`` subprocess (seconds).

    ``None`` means no limit. Env ``REPLAYT_RUN_HOOK_TIMEOUT`` overrides config; value ``<= 0``
    means unlimited. Default when unset: 120 seconds.
    """

    return _hook_timeout_seconds(cfg, env_var="REPLAYT_RUN_HOOK_TIMEOUT", config_key="run_hook_timeout")


def resume_hook_timeout_seconds(cfg: dict[str, Any]) -> float | None:
    """Wall-clock limit for the ``resume_hook`` subprocess (seconds).

    ``None`` means no limit. Env ``REPLAYT_RESUME_HOOK_TIMEOUT`` overrides config; value ``<= 0``
    means unlimited. Default when unset: 120 seconds.
    """

    return _hook_timeout_seconds(cfg, env_var="REPLAYT_RESUME_HOOK_TIMEOUT", config_key="resume_hook_timeout")


def export_hook_timeout_seconds(cfg: dict[str, Any]) -> float | None:
    """Wall-clock limit for the ``export_hook`` subprocess (seconds).

    ``None`` means no limit. Env ``REPLAYT_EXPORT_HOOK_TIMEOUT`` overrides config; value ``<= 0``
    means unlimited. Default when unset: 120 seconds.
    """

    return _hook_timeout_seconds(cfg, env_var="REPLAYT_EXPORT_HOOK_TIMEOUT", config_key="export_hook_timeout")


def seal_hook_timeout_seconds(cfg: dict[str, Any]) -> float | None:
    """Wall-clock limit for the ``seal_hook`` subprocess (seconds).

    ``None`` means no limit. Env ``REPLAYT_SEAL_HOOK_TIMEOUT`` overrides config; value ``<= 0``
    means unlimited. Default when unset: 120 seconds.
    """

    return _hook_timeout_seconds(cfg, env_var="REPLAYT_SEAL_HOOK_TIMEOUT", config_key="seal_hook_timeout")


def verify_seal_hook_timeout_seconds(cfg: dict[str, Any]) -> float | None:
    """Wall-clock limit for the ``verify_seal_hook`` subprocess (seconds).

    ``None`` means no limit. Env ``REPLAYT_VERIFY_SEAL_HOOK_TIMEOUT`` overrides config; value ``<= 0``
    means unlimited. Default when unset: 120 seconds.
    """

    return _hook_timeout_seconds(
        cfg, env_var="REPLAYT_VERIFY_SEAL_HOOK_TIMEOUT", config_key="verify_seal_hook_timeout"
    )


def min_replayt_version_report(cfg: dict[str, Any], *, installed: str) -> dict[str, Any]:
    """Summarize optional ``min_replayt_version`` from project config for doctor / ``replayt config``."""

    raw = cfg.get("min_replayt_version")
    if raw is None:
        s = ""
    else:
        s = str(raw).strip()
    if not s:
        return {
            "constraint": None,
            "constraint_source": "unset",
            "satisfied": True,
            "parse_error": None,
            "installed": installed,
        }
    from replayt.version_compare import replayt_release_tuple

    try:
        inst_t = replayt_release_tuple(installed)
        min_t = replayt_release_tuple(s)
    except ValueError as exc:
        return {
            "constraint": s,
            "constraint_source": "project_config:min_replayt_version",
            "satisfied": False,
            "parse_error": str(exc),
            "installed": installed,
        }
    return {
        "constraint": s,
        "constraint_source": "project_config:min_replayt_version",
        "satisfied": inst_t >= min_t,
        "parse_error": None,
        "installed": installed,
    }


def enforce_min_replayt_version_cli(cfg: dict[str, Any], *, installed: str) -> None:
    """Fail fast when project config requires a newer replayt than ``installed``."""

    report = min_replayt_version_report(cfg, installed=installed)
    if report["constraint"] is None:
        return
    if report["parse_error"]:
        raise typer.BadParameter(
            f"Invalid min_replayt_version {report['constraint']!r} in project config "
            f"({report['parse_error']}); fix [tool.replayt] / .replaytrc.toml (see docs/CONFIG.md)."
        )
    if not report["satisfied"]:
        raise typer.BadParameter(
            f"This project requires replayt>={report['constraint']} "
            f"(see [tool.replayt] min_replayt_version); installed {report['installed']}. "
            "Upgrade with pip install -U replayt or align your checkout."
        )


def parse_log_mode(log_mode: str) -> LogMode:
    key = log_mode.strip().lower()
    if key == "redacted":
        return LogMode.redacted
    if key == "full":
        return LogMode.full
    if key in {"structured_only", "structured-only"}:
        return LogMode.structured_only
    raise typer.BadParameter("log_mode must be redacted, full, or structured_only")
