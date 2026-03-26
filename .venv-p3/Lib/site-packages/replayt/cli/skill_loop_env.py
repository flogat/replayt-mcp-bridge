"""Environment contract for ``scripts/skill_release_loop*.py`` (exposed via ``replayt version --format json``)."""

from __future__ import annotations

from typing import Any

SKILL_LOOP_ENV_CONTRACT_SCHEMA = "replayt.skill_loop_env_contract.v1"

# Keys injected into --skill-command subprocesses (skill iterations).
SKILL_LOOP_MAIN_INJECTED_ENV_KEYS: tuple[str, ...] = (
    "REPO_ROOT",
    "SKILL_COMMAND_SHA256",
    "SKILL_ITERATION",
    "SKILL_INVOCATION_FILE",
    "SKILL_INVOCATION_REL",
    "SKILL_LOG_FILE",
    "SKILL_LOG_REL",
    "SKILL_MAX_ITERATIONS",
    "SKILL_NAME",
    "SKILL_PATH",
    "SKILL_PIPELINE_SHA256",
    "SKILL_PROMPT_FILE",
    "SKILL_PROMPT_REL",
    "SKILL_REQUESTED_NAME",
    "SKILL_ROOT",
    "SKILL_RUN_DIR",
    "SKILL_RUN_DIR_REL",
    "SKILL_RUN_STAMP",
    "SKILL_STEP_INDEX",
    "SKILL_STEP_TOTAL",
    "SKILL_TASK",
    "SKILL_TASK_SHA256",
)

# Fix-step invocations omit skill discovery fields (path / requested alias).
SKILL_LOOP_FIX_INJECTED_ENV_KEYS: tuple[str, ...] = (
    "REPO_ROOT",
    "SKILL_COMMAND_SHA256",
    "SKILL_ITERATION",
    "SKILL_INVOCATION_FILE",
    "SKILL_INVOCATION_REL",
    "SKILL_LOG_FILE",
    "SKILL_LOG_REL",
    "SKILL_MAX_ITERATIONS",
    "SKILL_NAME",
    "SKILL_PIPELINE_SHA256",
    "SKILL_PROMPT_FILE",
    "SKILL_PROMPT_REL",
    "SKILL_ROOT",
    "SKILL_RUN_DIR",
    "SKILL_RUN_DIR_REL",
    "SKILL_RUN_STAMP",
    "SKILL_STEP_INDEX",
    "SKILL_STEP_TOTAL",
    "SKILL_TASK",
    "SKILL_TASK_SHA256",
)

_SKILL_LOOP_ENV_KEY_DESCRIPTIONS: dict[str, str] = {
    "REPO_ROOT": "Absolute path to the repository root (resolved).",
    "SKILL_COMMAND_SHA256": "SHA-256 hex (UTF-8) of the raw --skill-command template string.",
    "SKILL_ITERATION": "1-based outer loop iteration index (string).",
    "SKILL_INVOCATION_FILE": "Absolute path to this step's replayt.skill_invocation.v1 sidecar (*.invocation.json).",
    "SKILL_INVOCATION_REL": (
        "Sidecar path relative to REPO_ROOT when under the repo, else absolute; "
        "POSIX separators (forward slashes) on all platforms."
    ),
    "SKILL_LOG_FILE": "Absolute path to the log file for this invocation.",
    "SKILL_LOG_REL": (
        "Log path relative to REPO_ROOT when under the repo, else absolute; "
        "POSIX separators (forward slashes) on all platforms."
    ),
    "SKILL_MAX_ITERATIONS": "Configured --max-iterations (string).",
    "SKILL_NAME": "Resolved skill folder name, or fix_check for automated fix prompts.",
    "SKILL_PATH": "Filesystem path to the skill folder or marker for fix_check (main loop only).",
    "SKILL_PIPELINE_SHA256": "SHA-256 hex of the ordered skill list for this run directory.",
    "SKILL_PROMPT_FILE": "Absolute path to the generated *.prompt.md file.",
    "SKILL_PROMPT_REL": (
        "Prompt path relative to REPO_ROOT when under the repo, else absolute; "
        "POSIX separators (forward slashes) on all platforms."
    ),
    "SKILL_REQUESTED_NAME": "CLI --skills name before alias resolution (main loop only).",
    "SKILL_ROOT": "Absolute path to the skill root directory (--skill-root).",
    "SKILL_RUN_DIR": "Absolute path to this skill-release run directory.",
    "SKILL_RUN_DIR_REL": (
        "Run directory relative to REPO_ROOT when under the repo, else absolute; "
        "POSIX separators (forward slashes) on all platforms."
    ),
    "SKILL_RUN_STAMP": "Basename of SKILL_RUN_DIR (for example YYYYMMDD-HHMMSS for default run folders).",
    "SKILL_STEP_INDEX": "1-based index within the skill list for this iteration (string); 0 for fix steps.",
    "SKILL_STEP_TOTAL": "Total skills in the pipeline (string); 0 for fix steps.",
    "SKILL_TASK": "Shared --task string for the outer loop.",
    "SKILL_TASK_SHA256": "SHA-256 hex (UTF-8) of SKILL_TASK for resume and idempotency gates.",
}


def build_skill_loop_env_contract() -> dict[str, Any]:
    """Stable JSON fragment for ``replayt version --format json``."""

    def rows(keys: tuple[str, ...]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for name in keys:
            desc = _SKILL_LOOP_ENV_KEY_DESCRIPTIONS.get(name)
            if not desc:
                msg = f"Missing skill-loop env description for {name!r}"
                raise KeyError(msg)
            out.append({"name": name, "description": desc})
        return out

    return {
        "schema": SKILL_LOOP_ENV_CONTRACT_SCHEMA,
        "main_injected_env": rows(SKILL_LOOP_MAIN_INJECTED_ENV_KEYS),
        "fix_injected_env": rows(SKILL_LOOP_FIX_INJECTED_ENV_KEYS),
    }
