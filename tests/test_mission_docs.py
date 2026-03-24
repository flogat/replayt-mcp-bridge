"""Contract tests for docs/MISSION.md and README discoverability."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = REPO_ROOT / "docs" / "MISSION.md"
README_PATH = REPO_ROOT / "README.md"


def test_mission_file_exists() -> None:
    assert MISSION_PATH.is_file(), "docs/MISSION.md must exist"


def test_mission_has_no_draft_placeholder_section() -> None:
    text = MISSION_PATH.read_text(encoding="utf-8")
    lower = text.lower()
    assert "## draft" not in lower
    assert "draft prompt" not in lower


def test_mission_states_bridge_primary_pattern_and_ecosystem_link() -> None:
    text = MISSION_PATH.read_text(encoding="utf-8")
    assert "**Primary pattern:**" in text
    assert "bridge" in text.lower()
    assert "REPLAYT_ECOSYSTEM_IDEA.md" in text


def test_mission_covers_users_scope_success_and_non_goals() -> None:
    text = MISSION_PATH.read_text(encoding="utf-8")
    assert "## Users and problem" in text
    assert "## What replayt provides" in text
    assert "## Scope vs upstream" in text
    assert "## Success metrics" in text
    assert "Non-goals" in text


def test_readme_links_mission_in_first_screenful() -> None:
    lines = README_PATH.read_text(encoding="utf-8").splitlines()
    head = "\n".join(lines[:30])
    assert "docs/MISSION.md" in head


def test_mission_defines_mcp_stdio_spec_and_acceptance() -> None:
    text = MISSION_PATH.read_text(encoding="utf-8")
    assert "## MCP server (stdio)" in text
    assert "stdio" in text.lower()
    assert "Acceptance criteria" in text
    assert "[project.scripts]" in text or "project.scripts" in text
    assert "python -m replayt_mcp_bridge" in text


def test_mission_defines_stdio_session_smoke_spec() -> None:
    text = MISSION_PATH.read_text(encoding="utf-8")
    assert "## Stdio MCP session integration smoke test" in text
    assert "ClientSession" in text
    assert "stdio_client" in text
    assert "replayt_version_info" in text
    assert "ARCHITECTURE.md" in text


def test_readme_quick_start_orients_mcp_hosts() -> None:
    text = README_PATH.read_text(encoding="utf-8")
    assert "## Quick start" in text
    assert "MCP" in text
    assert "stdio" in text.lower()
    assert "docs/MISSION.md#mcp-server-stdio" in text
