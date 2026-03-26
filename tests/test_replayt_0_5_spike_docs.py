"""Contract tests for docs/REPLAYT_0_5_COMPATIBILITY_SPIKE.md (maintainer spike record)."""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPIKE_PATH = REPO_ROOT / "docs" / "REPLAYT_0_5_COMPATIBILITY_SPIKE.md"
README_PATH = REPO_ROOT / "README.md"
MISSION_PATH = REPO_ROOT / "docs" / "MISSION.md"
DESIGN_PATH = REPO_ROOT / "docs" / "DESIGN_PRINCIPLES.md"
ARCH_PATH = REPO_ROOT / "docs" / "ARCHITECTURE.md"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


def _replayt_dependency_from_pyproject() -> str:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    deps: list[str] = data["project"]["dependencies"]
    for line in deps:
        stripped = line.strip()
        if stripped.startswith("replayt"):
            return stripped
    raise AssertionError("pyproject.toml [project].dependencies must list replayt")


def test_spike_doc_exists() -> None:
    assert SPIKE_PATH.is_file(), "docs/REPLAYT_0_5_COMPATIBILITY_SPIKE.md must exist"


def test_spike_doc_has_core_sections() -> None:
    text = SPIKE_PATH.read_text(encoding="utf-8")
    for heading in (
        "## Status summary (executed spike)",
        "## How to re-run this spike",
        "## Bridge ↔ replayt API touchpoints (break analysis)",
        "## Draft migration note (for CHANGELOG when widening)",
    ):
        assert heading in text, f"Spike doc must include {heading!r}"


def test_spike_doc_declared_range_matches_pyproject() -> None:
    dep = _replayt_dependency_from_pyproject()
    text = SPIKE_PATH.read_text(encoding="utf-8")
    assert dep in text, (
        "Spike status summary must quote the same replayt dependency line as pyproject.toml"
    )


def test_spike_doc_mentions_key_replayt_touchpoints() -> None:
    """Guard the break-analysis table against silent truncation."""
    text = SPIKE_PATH.read_text(encoding="utf-8")
    for needle in (
        "load_target",
        "validation_report",
        "workflow_to_mermaid",
        "replayt.__version_tuple__",
        "SQLiteStore",
        "JSONLStore",
    ):
        assert needle in text, f"Spike API touchpoints should mention {needle!r}"


def test_maintainer_docs_link_spike_doc() -> None:
    needle = "REPLAYT_0_5_COMPATIBILITY_SPIKE.md"
    for path, label in (
        (README_PATH, "README.md"),
        (MISSION_PATH, "docs/MISSION.md"),
        (DESIGN_PATH, "docs/DESIGN_PRINCIPLES.md"),
        (ARCH_PATH, "docs/ARCHITECTURE.md"),
    ):
        assert needle in path.read_text(encoding="utf-8"), (
            f"{label} must link to {needle}"
        )


def test_mission_defines_replayt_0_5_spike_section() -> None:
    text = MISSION_PATH.read_text(encoding="utf-8")
    assert "## Replayt minor-line compatibility spike (0.5.x)" in text
    assert "test_version_contract_docs.py" in text
    assert "replayt-floor" in text
