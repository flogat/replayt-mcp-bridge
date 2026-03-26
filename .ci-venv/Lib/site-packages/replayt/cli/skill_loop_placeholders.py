"""Placeholder contract for ``scripts/skill_release_loop*.py`` (exposed via ``replayt version --format json``)."""

from __future__ import annotations

from typing import Any

SKILL_LOOP_PLACEHOLDER_CONTRACT_SCHEMA = "replayt.skill_loop_placeholder_contract.v1"


def _row(*, name: str, description: str) -> dict[str, str]:
    return {"name": name, "description": description}


def build_skill_loop_placeholder_contract() -> dict[str, Any]:
    """Stable JSON fragment for ``replayt version --format json``.

    Documents template keys for :func:`str.format_map`-style expansion in the maintainer scripts.
    Every listed name also has a shell-quoted sibling ``{name}_q`` (for example ``prompt_file_q``).
    """

    skill_command = [
        _row(
            name="invocation_file",
            description=(
                "Absolute path to this step's replayt.skill_invocation.v1 sidecar (*.invocation.json). "
                "Same as env SKILL_INVOCATION_FILE."
            ),
        ),
        _row(
            name="invocation_rel",
            description=(
                "Sidecar path relative to REPO_ROOT when under the repo, else absolute; "
                "POSIX separators (forward slashes) on all platforms. Same as env SKILL_INVOCATION_REL."
            ),
        ),
        _row(
            name="iteration",
            description=(
                "1-based outer loop iteration index (string). Same as env SKILL_ITERATION."
            ),
        ),
        _row(
            name="log_file",
            description="Absolute path to this invocation's log file.",
        ),
        _row(
            name="log_rel",
            description=(
                "Log path relative to REPO_ROOT when under the repo, else absolute; "
                "POSIX separators (forward slashes) on all platforms. Same as env SKILL_LOG_REL."
            ),
        ),
        _row(
            name="max_iterations",
            description="Configured --max-iterations (string). Same as env SKILL_MAX_ITERATIONS.",
        ),
        _row(
            name="pipeline_sha256",
            description=(
                "SHA-256 hex of the ordered --skills list for this run directory. "
                "Same as env SKILL_PIPELINE_SHA256."
            ),
        ),
        _row(
            name="prompt_file",
            description="Absolute path to the generated *.prompt.md file.",
        ),
        _row(
            name="prompt_rel",
            description=(
                "Prompt path relative to REPO_ROOT when under the repo, else absolute; "
                "POSIX separators (forward slashes) on all platforms. Same as env SKILL_PROMPT_REL."
            ),
        ),
        _row(
            name="repo",
            description=(
                "Repository root path string for template expansion. "
                "REPO_ROOT on skill subprocesses is the resolved absolute path (may differ when the loop is "
                "started with a non-absolute path)."
            ),
        ),
        _row(
            name="run_dir",
            description="Absolute path to the skill-release run directory. Same as env SKILL_RUN_DIR.",
        ),
        _row(
            name="run_dir_rel",
            description=(
                "Run directory relative to REPO_ROOT when under the repo, else absolute; "
                "POSIX separators (forward slashes) on all platforms. Same as env SKILL_RUN_DIR_REL."
            ),
        ),
        _row(
            name="run_stamp",
            description=(
                "Basename of the run directory (for example YYYYMMDD-HHMMSS). Same as env SKILL_RUN_STAMP."
            ),
        ),
        _row(
            name="skill",
            description=(
                "Resolved skill folder name for normal steps; fix_check or fix_pre_tag_ci for automated fix rounds. "
                "Same as env SKILL_NAME."
            ),
        ),
        _row(
            name="skill_command_sha256",
            description=(
                "SHA-256 hex (UTF-8) of the raw --skill-command template string. Same as env SKILL_COMMAND_SHA256."
            ),
        ),
        _row(
            name="skill_path",
            description=(
                "Filesystem path to the skill's SKILL.md for normal steps; literal fix_check or fix_pre_tag_ci "
                "for fix rounds. Omitted from fix-step env as SKILL_PATH (see skill_loop_env_contract)."
            ),
        ),
        _row(
            name="skill_root",
            description="Absolute path to --skill-root. Same as env SKILL_ROOT.",
        ),
        _row(
            name="step_index",
            description=(
                "1-based position in the skill list (string); 0 for fix steps. Same as env SKILL_STEP_INDEX."
            ),
        ),
        _row(
            name="step_total",
            description=(
                "Total skills in the pipeline (string); 0 for fix steps. Same as env SKILL_STEP_TOTAL."
            ),
        ),
        _row(
            name="task",
            description=(
                "String passed into the template for {task}. For normal skills this is the full shared --task. "
                "For fix_check / fix_pre_tag_ci it is the short fix instruction only (matches SKILL_TASK for "
                "that subprocess). The outer loop task digest is always task_sha256 / SKILL_TASK_SHA256."
            ),
        ),
        _row(
            name="task_sha256",
            description=(
                "SHA-256 hex (UTF-8) of the outer --task string for resume/idempotency. Same as env "
                "SKILL_TASK_SHA256 on every subprocess including fix rounds."
            ),
        ),
    ]

    check_command = [
        _row(
            name="iteration",
            description="1-based outer loop iteration index (string) while the check runs.",
        ),
        _row(
            name="repo",
            description="Repository root path (string). Set as REPO_ROOT in the check subprocess environment.",
        ),
    ]

    return {
        "schema": SKILL_LOOP_PLACEHOLDER_CONTRACT_SCHEMA,
        "notes": (
            "Templates use Python str.format_map; unknown keys raise before spawn. "
            "Each name listed under skill_command_placeholders and check_command_placeholders "
            "also supports a {name}_q variant with shell quoting for argv construction."
        ),
        "skill_command_placeholders": skill_command,
        "check_command_placeholders": check_command,
    }
