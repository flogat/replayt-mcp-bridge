"""Keep pyproject.toml, DESIGN_PRINCIPLES, and the supported replayt range in sync."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
DESIGN_PATH = REPO_ROOT / "docs" / "DESIGN_PRINCIPLES.md"

_EXPECTED_REPLAYT_SPEC = ">=0.4.25,<0.5"


def _replayt_dependency_from_pyproject() -> str:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    deps: list[str] = data["project"]["dependencies"]
    for line in deps:
        stripped = line.strip()
        if stripped.startswith("replayt"):
            return stripped
    raise AssertionError("pyproject.toml [project].dependencies must list replayt")


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
