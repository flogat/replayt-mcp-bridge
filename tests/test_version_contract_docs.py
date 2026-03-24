"""Keep pyproject.toml, DESIGN_PRINCIPLES, README, CHANGELOG, CONTRIBUTING, and CI in sync."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
DESIGN_PATH = REPO_ROOT / "docs" / "DESIGN_PRINCIPLES.md"
README_PATH = REPO_ROOT / "README.md"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"
CONTRIBUTING_PATH = REPO_ROOT / "CONTRIBUTING.md"
CI_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"

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
