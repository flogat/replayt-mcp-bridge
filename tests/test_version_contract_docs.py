"""Keep pyproject.toml, DESIGN_PRINCIPLES, README, CHANGELOG, CONTRIBUTING, CI, SECURITY, and DEPENDENCY_AUDIT in sync."""

from __future__ import annotations

import importlib.util
import re
import shlex
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
DESIGN_PATH = REPO_ROOT / "docs" / "DESIGN_PRINCIPLES.md"
README_PATH = REPO_ROOT / "README.md"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"
CONTRIBUTING_PATH = REPO_ROOT / "CONTRIBUTING.md"
CI_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEPENDABOT_PATH = REPO_ROOT / ".github" / "dependabot.yml"
MISSION_PATH = REPO_ROOT / "docs" / "MISSION.md"
DEPENDENCY_AUDIT_PATH = REPO_ROOT / "docs" / "DEPENDENCY_AUDIT.md"
SECURITY_PATH = REPO_ROOT / "docs" / "SECURITY.md"

_EXPECTED_REPLAYT_SPEC = ">=0.4.25,<0.5"

# Must match .github/workflows/ci.yml test.matrix.python-version (CI-tested CPython minors).
_EXPECTED_CI_PYTHON_VERSIONS = ("3.11", "3.12", "3.13")


def _replayt_dependency_from_pyproject() -> str:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    deps: list[str] = data["project"]["dependencies"]
    for line in deps:
        stripped = line.strip()
        if stripped.startswith("replayt"):
            return stripped
    raise AssertionError("pyproject.toml [project].dependencies must list replayt")


def _project_version_from_pyproject() -> str:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _replayt_floor_version(dep_line: str) -> str:
    m = re.search(r">=(\d+\.\d+\.\d+)", dep_line)
    assert m is not None, f"Could not parse replayt lower bound from {dep_line!r}"
    return m.group(1)


def _canonical_pip_audit_command_from_dependency_audit() -> str:
    text = DEPENDENCY_AUDIT_PATH.read_text(encoding="utf-8")
    m = re.search(
        r"\*\*Canonical command\*\*.*?\n```bash\n([^\n]+)\n```",
        text,
        flags=re.DOTALL,
    )
    assert m is not None, (
        "docs/DEPENDENCY_AUDIT.md must document a **Canonical command** bash fence with pip-audit"
    )
    return m.group(1).strip()


def _ci_supply_chain_block(ci_text: str) -> str:
    assert "supply-chain:" in ci_text, (
        ".github/workflows/ci.yml must define a supply-chain job"
    )
    return ci_text.split("supply-chain:", 1)[1]


def _ci_test_job_ruff_pytest_run_lines(ci_text: str) -> tuple[str, str, str]:
    """The three ``run:`` lines after ``pip install`` in the Linux ``test`` job."""
    body = _ci_job_body(ci_text, "test", "test-windows")
    runs = re.findall(r"^\s+run:\s*(.+)$", body, re.MULTILINE)
    assert len(runs) == 4, (
        "CI test job must have four run: steps "
        "(install + ruff check + ruff format + pytest)"
    )
    assert "pip install" in runs[0]
    return (runs[1], runs[2], runs[3])


def _load_run_ci_checks_module():
    path = REPO_ROOT / "scripts" / "run_ci_checks.py"
    spec = importlib.util.spec_from_file_location("run_ci_checks", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ci_job_body(ci_text: str, job: str, next_job: str | None) -> str:
    """YAML slice from `  {job}:` through the line before `  {next_job}:` (jobs: indentation)."""
    marker = f"  {job}:"
    assert marker in ci_text, f".github/workflows/ci.yml must define job {job!r}"
    tail = ci_text.split(marker, 1)[1]
    if next_job is None:
        return tail
    nxt = f"  {next_job}:"
    assert nxt in tail, (
        f".github/workflows/ci.yml must define job {next_job!r} after {job!r}"
    )
    return tail.split(nxt, 1)[0]


def test_pyproject_declares_replayt_in_supported_range() -> None:
    spec = _replayt_dependency_from_pyproject()
    assert spec == f"replayt{_EXPECTED_REPLAYT_SPEC}", (
        f"Expected replayt dependency {_EXPECTED_REPLAYT_SPEC!r} in pyproject.toml; got {spec!r}"
    )


def test_design_principles_states_same_replayt_range_as_pyproject() -> None:
    text = DESIGN_PATH.read_text(encoding="utf-8")
    assert _EXPECTED_REPLAYT_SPEC in text, (
        "docs/DESIGN_PRINCIPLES.md must document the same replayt range as pyproject.toml"
    )
    assert re.search(
        rf"`{re.escape(_EXPECTED_REPLAYT_SPEC)}`",
        text,
    ), (
        "DESIGN_PRINCIPLES should quote the replayt range in backticks for discoverability"
    )


def test_readme_compatibility_matches_pyproject_replayt_and_version() -> None:
    dep = _replayt_dependency_from_pyproject()
    version = _project_version_from_pyproject()
    readme = README_PATH.read_text(encoding="utf-8")
    assert "## Compatibility with replayt" in readme
    assert dep in readme, (
        "README must repeat the exact replayt dependency line from pyproject.toml"
    )
    assert f"| {version} " in readme, (
        "README compatibility table must list the bridge version from [project].version"
    )


def test_readme_python_paragraph_lists_each_ci_matrix_minor() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    assert "**Python:**" in readme
    for ver in _EXPECTED_CI_PYTHON_VERSIONS:
        assert ver in readme, (
            f"README must mention CPython minor {ver!r} alongside other CI-tested versions "
            f"(expected: {_EXPECTED_CI_PYTHON_VERSIONS})"
        )


def test_contributing_mentions_each_ci_matrix_minor() -> None:
    text = CONTRIBUTING_PATH.read_text(encoding="utf-8")
    for ver in _EXPECTED_CI_PYTHON_VERSIONS:
        assert ver in text, (
            f"CONTRIBUTING must mention CPython minor {ver!r} for local/CI parity "
            f"(expected: {_EXPECTED_CI_PYTHON_VERSIONS})"
        )


def test_changelog_has_release_section_for_package_version() -> None:
    version = _project_version_from_pyproject()
    text = CHANGELOG_PATH.read_text(encoding="utf-8")
    assert "Keep a Changelog" in text
    assert f"## [{version}]" in text
    assert _EXPECTED_REPLAYT_SPEC in text, (
        "CHANGELOG should document the declared replayt range for integrators"
    )


def test_contributing_releases_covers_changelog_readme_and_ci_pins() -> None:
    text = CONTRIBUTING_PATH.read_text(encoding="utf-8")
    assert "## Releases" in text
    for needle in (
        "CHANGELOG.md",
        "pyproject.toml",
        "README.md",
        "ci.yml",
        "replayt-floor",
    ):
        assert needle in text, f"CONTRIBUTING Releases section should mention {needle}"


def test_ci_matrix_lists_expected_python_versions() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    for ver in _EXPECTED_CI_PYTHON_VERSIONS:
        assert f'"{ver}"' in ci, (
            f".github/workflows/ci.yml matrix must include python-version {ver!r} "
            f"(expected CI minors: {_EXPECTED_CI_PYTHON_VERSIONS})"
        )


def test_ci_pytest_excludes_network_marked_tests_by_default() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    needle = 'pytest -q -m "not network"'
    assert ci.count(needle) == 3, (
        "Linux test, Windows test, and replayt-floor jobs must run the same "
        f"default pytest invocation ({needle!r})"
    )


def test_run_ci_checks_script_matches_ci_test_job_steps() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    r1, r2, r3 = _ci_test_job_ruff_pytest_run_lines(ci)
    expected = (
        shlex.split(r1.strip(), posix=True),
        shlex.split(r2.strip(), posix=True),
        shlex.split(r3.strip(), posix=True),
    )
    mod = _load_run_ci_checks_module()
    assert mod.CI_CHECK_STEPS == expected, (
        "scripts/run_ci_checks.py CI_CHECK_STEPS must match the ruff/pytest "
        "run lines in .github/workflows/ci.yml test job"
    )


def test_ci_includes_windows_test_job() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    assert "test-windows:" in ci, (
        ".github/workflows/ci.yml must define a test-windows job for Windows CI coverage"
    )
    assert "runs-on: windows-latest" in ci, (
        "Windows CI job must use runs-on: windows-latest (see docs/MISSION.md Windows CI runner)"
    )
    # Single Windows Python minor (3.12) — keep in sync with README / CONTRIBUTING.
    win_block = ci.split("test-windows:", 1)[1]
    if "replayt-floor:" in win_block:
        win_block = win_block.split("replayt-floor:", 1)[0]
    assert 'python-version: "3.12"' in win_block, (
        'test-windows job must pin python-version: "3.12"'
    )
    for step in (
        'pip install -e ".[dev]"',
        "ruff check src tests",
        "ruff format --check src tests",
        'pytest -q -m "not network"',
    ):
        assert step in win_block, f"test-windows job must run {step!r}"
    assert "cache: pip" in win_block
    assert "cache-dependency-path: pyproject.toml" in win_block


def test_pyproject_classifiers_list_ci_python_minors() -> None:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    classifiers: list[str] = list(data["project"].get("classifiers") or [])
    for ver in _EXPECTED_CI_PYTHON_VERSIONS:
        needle = f"Programming Language :: Python :: {ver}"
        assert needle in classifiers, (
            f"pyproject.toml [project].classifiers must include {needle!r} for each CI matrix minor"
        )


def test_ci_reinstalls_replayt_floor_matching_pyproject_minimum() -> None:
    dep = _replayt_dependency_from_pyproject()
    floor = _replayt_floor_version(dep)
    ci = CI_PATH.read_text(encoding="utf-8")
    assert f"replayt=={floor}" in ci, (
        f".github/workflows/ci.yml must reinstall replayt=={floor} to match pyproject lower bound"
    )
    assert "replayt-floor:" in ci


def test_dependency_audit_local_reproduction_uses_same_pip_audit_as_canonical() -> None:
    canonical = _canonical_pip_audit_command_from_dependency_audit()
    text = DEPENDENCY_AUDIT_PATH.read_text(encoding="utf-8")
    assert canonical.startswith("pip-audit"), (
        "Canonical command must be a pip-audit invocation"
    )
    local = text.split("## Local reproduction", 1)[1]
    m = re.search(r"```bash\n(.*?)```", local, flags=re.DOTALL)
    assert m is not None, (
        "docs/DEPENDENCY_AUDIT.md Local reproduction must include a bash fence"
    )
    lines = [ln.strip() for ln in m.group(1).strip().splitlines() if ln.strip()]
    audit_lines = [ln for ln in lines if ln.startswith("pip-audit")]
    assert audit_lines == [canonical], (
        "Local reproduction pip-audit line must match the **Canonical command** block "
        f"(expected {canonical!r}, got {audit_lines!r})"
    )


def test_ci_supply_chain_pip_audit_matches_dependency_audit_canonical_command() -> None:
    expected = _canonical_pip_audit_command_from_dependency_audit()
    ci = CI_PATH.read_text(encoding="utf-8")
    block = _ci_supply_chain_block(ci)
    assert f"run: {expected}" in block, (
        ".github/workflows/ci.yml supply-chain job must run the same command as "
        f"docs/DEPENDENCY_AUDIT.md **Canonical command** (expected `run: {expected}`)"
    )


def test_ci_supply_chain_job_matrix_matches_test_job_python_versions() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    block = _ci_supply_chain_block(ci)
    for ver in _EXPECTED_CI_PYTHON_VERSIONS:
        assert f'"{ver}"' in block, (
            ".github/workflows/ci.yml supply-chain matrix must include "
            f"python-version {ver!r} (expected {_EXPECTED_CI_PYTHON_VERSIONS})"
        )


def test_ci_supply_chain_installs_editable_dev_extras() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    block = _ci_supply_chain_block(ci)
    assert 'pip install -e ".[dev]"' in block, (
        'supply-chain job must install the package with pip install -e ".[dev]" before pip-audit'
    )


def test_contributing_includes_canonical_pip_audit_command() -> None:
    canonical = _canonical_pip_audit_command_from_dependency_audit()
    text = CONTRIBUTING_PATH.read_text(encoding="utf-8")
    assert canonical in text, (
        "CONTRIBUTING.md must include the exact pip-audit line from "
        "docs/DEPENDENCY_AUDIT.md **Canonical command** "
        f"(expected substring {canonical!r})"
    )


def test_security_dependency_scanning_links_blocking_policy() -> None:
    text = SECURITY_PATH.read_text(encoding="utf-8")
    sec = text.split("## Dependency vulnerability scanning (CI)", 1)[1]
    assert "DEPENDENCY_AUDIT.md#blocking-ci-vs-advisory" in sec.split("##", 1)[0], (
        "docs/SECURITY.md § Dependency vulnerability scanning must link "
        "DEPENDENCY_AUDIT.md#blocking-ci-vs-advisory"
    )


def test_ci_test_jobs_do_not_invoke_pip_audit() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    for job, next_job in (
        ("test", "test-windows"),
        ("test-windows", "replayt-floor"),
        ("replayt-floor", "supply-chain"),
    ):
        body = _ci_job_body(ci, job, next_job)
        assert "pip-audit" not in body, (
            f"CI job {job!r} must not invoke pip-audit "
            "(keep the scanner in supply-chain only; default pytest jobs stay offline-friendly)"
        )


def test_dependabot_yml_configures_github_actions_weekly_with_group() -> None:
    assert DEPENDABOT_PATH.is_file(), ".github/dependabot.yml must exist"
    text = DEPENDABOT_PATH.read_text(encoding="utf-8")
    assert "version: 2" in text
    assert 'package-ecosystem: "github-actions"' in text
    assert 'directory: "/"' in text
    assert "interval: weekly" in text.replace('"', "").replace("'", ""), (
        "dependabot.yml must set schedule.interval to weekly"
    )
    assert "groups:" in text
    assert "github-actions:" in text
    assert "patterns:" in text
    assert '"*"' in text or "'*'" in text


_WINDOWS_CI_RUNNER_HEADING = "## Windows CI runner (install and pytest smoke)"


def test_mission_windows_ci_runner_records_shipped_status_and_contract_test() -> None:
    mission = MISSION_PATH.read_text(encoding="utf-8")
    sec = mission.split(_WINDOWS_CI_RUNNER_HEADING, 1)[1].split(
        "### Backlog traceability", 1
    )[0]
    assert "**Implementation status (shipped):**" in sec
    assert "test-windows" in sec
    assert "test_ci_includes_windows_test_job" in sec


def test_mission_dependabot_section_records_shipped_status() -> None:
    mission = MISSION_PATH.read_text(encoding="utf-8")
    sec = mission.split("## Dependabot (or equivalent) for GitHub Actions pins", 1)[
        1
    ].split("### Backlog traceability", 1)[0]
    assert "**Implementation status (shipped):**" in sec
    assert "dependabot.yml" in sec


def test_contributing_documents_dependabot_and_separates_pip_audit() -> None:
    text = CONTRIBUTING_PATH.read_text(encoding="utf-8")
    assert "## GitHub Actions pin updates (Dependabot)" in text
    assert ".github/dependabot.yml" in text
    assert "docs/MISSION.md#dependabot-or-equivalent-for-github-actions-pins" in text
    assert "docs/MISSION.md#ci-dependency-vulnerability-scanning-supply-chain" in text
    assert "docs/DEPENDENCY_AUDIT.md" in text
    assert "pip-audit" in text


_REPLAYT_MINOR_LINE_PLAYBOOK_HEADING = (
    "## Replayt minor-line upgrade playbook (backlog spec)"
)
_REPLAYT_MINOR_LINE_PLAYBOOK_FRAGMENT = (
    "docs/MISSION.md#replayt-minor-line-upgrade-playbook-backlog-spec"
)


def test_mission_replayt_minor_line_upgrade_playbook_records_shipped_status() -> None:
    mission = MISSION_PATH.read_text(encoding="utf-8")
    sec = mission.split(_REPLAYT_MINOR_LINE_PLAYBOOK_HEADING, 1)[1].split(
        "### Backlog traceability", 1
    )[0]
    assert "**Implementation status:** **Shipped**" in sec


def test_mission_replayt_minor_line_upgrade_playbook_lists_ordered_checklist_items() -> (
    None
):
    mission = MISSION_PATH.read_text(encoding="utf-8")
    sec = mission.split(_REPLAYT_MINOR_LINE_PLAYBOOK_HEADING, 1)[1].split(
        "### Backlog traceability", 1
    )[0]
    for label in (
        "**Dependency specification**",
        "**Compatibility table**",
        "**Changelog**",
        "**CI floor pin job**",
        "**MCP_TOOLS mapping review**",
        "**Contract and schema tests**",
    ):
        assert label in sec, (
            f"docs/MISSION.md replayt minor-line playbook must retain checklist label {label!r}"
        )


def test_readme_and_contributing_link_mission_replayt_minor_line_playbook() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    contributing = CONTRIBUTING_PATH.read_text(encoding="utf-8")
    assert _REPLAYT_MINOR_LINE_PLAYBOOK_FRAGMENT in readme
    assert _REPLAYT_MINOR_LINE_PLAYBOOK_FRAGMENT in contributing
