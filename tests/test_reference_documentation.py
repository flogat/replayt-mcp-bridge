"""Tests for optional replayt reference docs mirror and refresh script helpers."""

from __future__ import annotations

import importlib.util
import io
import re
import tarfile
import tomllib
from pathlib import Path

import pytest

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


def _synthetic_sdist_bytes(
    *,
    version: str = "9.9.9",
    readme: bytes = b"# synthetic readme\n",
    license_bytes: bytes = b"License text\n",
) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
        info_r = tarfile.TarInfo(name=f"replayt-{version}/README.md")
        info_r.size = len(readme)
        tf.addfile(info_r, io.BytesIO(readme))
        info_l = tarfile.TarInfo(name=f"replayt-{version}/LICENSE")
        info_l.size = len(license_bytes)
        tf.addfile(info_l, io.BytesIO(license_bytes))
    return buffer.getvalue()


def test_reference_readme_documents_optional_mirror_and_bridge_contracts() -> None:
    text = REF_DOC_README.read_text(encoding="utf-8")
    assert "optional" in text.lower()
    assert "scripts/refresh_replayt_reference_docs.py" in text
    assert "--expected-sha256" in text
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
    tgz.write_bytes(
        _synthetic_sdist_bytes(readme=readme, license_bytes=license_bytes)
    )
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


def test_refresh_script_help_mentions_expected_sha256(capsys: pytest.CaptureFixture[str]) -> None:
    mod = _load_refresh_module()
    with pytest.raises(SystemExit) as excinfo:
        mod.main(["--help"])
    assert excinfo.value.code == 0
    assert "--expected-sha256" in capsys.readouterr().out


def test_main_rejects_malformed_expected_sha256_before_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load_refresh_module()
    monkeypatch.setattr(mod, "repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(
        mod,
        "pypi_sdist_url",
        lambda version: (_ for _ in ()).throw(AssertionError("should not fetch metadata")),
    )
    monkeypatch.setattr(
        mod,
        "download_sdist_bytes",
        lambda url: (_ for _ in ()).throw(AssertionError("should not download archive")),
    )

    with pytest.raises(SystemExit, match="Invalid --expected-sha256"):
        mod.main(["--version", "9.9.9", "--expected-sha256", "not-a-digest"])


def test_main_accepts_matching_expected_sha256_and_writes_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mod = _load_refresh_module()
    version = "9.9.9"
    archive_bytes = _synthetic_sdist_bytes(version=version)
    expected_sha256 = mod.sha256_digest_hex(archive_bytes)

    monkeypatch.setattr(mod, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(mod, "pypi_sdist_url", lambda version: "https://example.test/replayt.tgz")
    monkeypatch.setattr(mod, "download_sdist_bytes", lambda url: archive_bytes)

    mod.main(["--version", version, "--expected-sha256", expected_sha256])

    dest = (
        tmp_path
        / "docs"
        / "reference-documentation"
        / "snapshots"
        / f"replayt-{version}"
    )
    assert (dest / "README.md").read_text(encoding="utf-8") == "# synthetic readme\n"
    assert (dest / "LICENSE").read_text(encoding="utf-8") == "License text\n"
    assert (dest / "ATTRIBUTION.md").is_file()
    assert (
        f"Updated docs/reference-documentation/snapshots/replayt-{version}"
        in capsys.readouterr().out
    )


def test_main_rejects_mismatched_expected_sha256_before_overwriting_snapshot_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mod = _load_refresh_module()
    version = "9.9.9"
    archive_bytes = _synthetic_sdist_bytes(version=version)
    wrong_sha256 = "0" * 64
    dest = (
        tmp_path
        / "docs"
        / "reference-documentation"
        / "snapshots"
        / f"replayt-{version}"
    )
    dest.mkdir(parents=True)
    original_files = {
        "README.md": "existing readme\n",
        "LICENSE": "existing license\n",
        "ATTRIBUTION.md": "existing attribution\n",
    }
    for name, body in original_files.items():
        (dest / name).write_text(body, encoding="utf-8")

    monkeypatch.setattr(mod, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(mod, "pypi_sdist_url", lambda version: "https://example.test/replayt.tgz")
    monkeypatch.setattr(mod, "download_sdist_bytes", lambda url: archive_bytes)

    with pytest.raises(SystemExit, match="SHA-256 mismatch"):
        mod.main(["--version", version, "--expected-sha256", wrong_sha256])

    for name, body in original_files.items():
        assert (dest / name).read_text(encoding="utf-8") == body
