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
