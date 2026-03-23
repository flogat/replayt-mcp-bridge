"""Tests for optional replayt reference docs mirror and refresh script helpers."""

from __future__ import annotations

import importlib.util
import io
import re
import tarfile
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REF_DOC_README = REPO_ROOT / "docs" / "reference-documentation" / "README.md"
README_MAIN = REPO_ROOT / "README.md"
SCRIPTS_REFRESH = REPO_ROOT / "scripts" / "refresh_replayt_reference_docs.py"


def _load_refresh_module():
    spec = importlib.util.spec_from_file_location(
        "refresh_replayt_reference_docs", SCRIPTS_REFRESH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _replayt_floor_from_pyproject() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for line in data["project"]["dependencies"]:
        stripped = line.strip()
        if stripped.startswith("replayt"):
            m = re.search(r">=(\d+\.\d+\.\d+)", stripped)
            assert m is not None, (
                f"Could not parse replayt lower bound from {stripped!r}"
            )
            return m.group(1)
    raise AssertionError("pyproject.toml [project].dependencies must list replayt")


def test_reference_readme_documents_optional_mirror_and_bridge_contracts() -> None:
    text = REF_DOC_README.read_text(encoding="utf-8")
    assert "optional" in text.lower()
    assert "scripts/refresh_replayt_reference_docs.py" in text
    assert "MCP_TOOLS.md" in text
    assert "MISSION.md" in text
    assert "snapshots/" in text


def test_main_readme_points_at_reference_documentation() -> None:
    text = README_MAIN.read_text(encoding="utf-8")
    assert "docs/reference-documentation/" in text


def test_snapshot_directory_matches_replayt_floor() -> None:
    floor = _replayt_floor_from_pyproject()
    snap = (
        REPO_ROOT
        / "docs"
        / "reference-documentation"
        / "snapshots"
        / f"replayt-{floor}"
    )
    assert snap.is_dir()
    for name in ("README.md", "LICENSE", "ATTRIBUTION.md"):
        assert (snap / name).is_file(), f"Expected {snap / name}"


def test_attribution_lists_version_and_pypi_source() -> None:
    floor = _replayt_floor_from_pyproject()
    attr = (
        REPO_ROOT
        / "docs"
        / "reference-documentation"
        / "snapshots"
        / f"replayt-{floor}"
        / "ATTRIBUTION.md"
    ).read_text(encoding="utf-8")
    assert floor in attr
    assert f"https://pypi.org/project/replayt/{floor}/" in attr


def test_default_version_from_pyproject_matches_floor() -> None:
    mod = _load_refresh_module()
    assert (
        mod.default_version_from_pyproject(REPO_ROOT) == _replayt_floor_from_pyproject()
    )


def test_extract_readme_license_from_synthetic_sdist(tmp_path: Path) -> None:
    mod = _load_refresh_module()
    tgz = tmp_path / "fake-sdist.tar.gz"
    readme = b"# synthetic readme\n"
    license_bytes = b"License text\n"
    with tarfile.open(tgz, "w:gz") as tf:
        info_r = tarfile.TarInfo(name="replayt-9.9.9/README.md")
        info_r.size = len(readme)
        tf.addfile(info_r, io.BytesIO(readme))
        info_l = tarfile.TarInfo(name="replayt-9.9.9/LICENSE")
        info_l.size = len(license_bytes)
        tf.addfile(info_l, io.BytesIO(license_bytes))
    out = tmp_path / "extracted"
    mod.extract_readme_license(tgz, out)
    assert (out / "README.md").read_bytes() == readme
    assert (out / "LICENSE").read_bytes() == license_bytes


def test_write_attribution_names_version_and_pypi_files_link(tmp_path: Path) -> None:
    mod = _load_refresh_module()
    mod.write_attribution(tmp_path, "1.2.3")
    body = (tmp_path / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert "`1.2.3`" in body
    assert "https://pypi.org/project/replayt/1.2.3/#files" in body
