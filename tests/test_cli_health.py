"""Subprocess tests for the ``health`` install probe (no MCP session)."""

from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _console_script_path() -> Path:
    name = "replayt-mcp-bridge.exe" if sys.platform == "win32" else "replayt-mcp-bridge"
    scripts_dir = Path(sysconfig.get_path("scripts"))
    primary = scripts_dir / name
    if primary.is_file():
        return primary
    exe_dir = Path(sys.executable).resolve().parent
    same_dir = exe_dir / name
    if same_dir.is_file():
        return same_dir
    if sys.platform == "win32":
        under_scripts = exe_dir / "Scripts" / name
        if under_scripts.is_file():
            return under_scripts
    return primary


def _pythonpath_with_overlay(overlay: Path) -> str:
    prev = os.environ.get("PYTHONPATH", "")
    return f"{overlay}{os.pathsep}{prev}" if prev else str(overlay)


def test_health_module_subprocess_exit_zero() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "replayt_mcp_bridge", "health"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "replayt-mcp-bridge health: ok" in proc.stderr
    assert "replayt_mcp_bridge.health.ok" in proc.stderr


def test_health_console_script_subprocess_exit_zero() -> None:
    cmd = _console_script_path()
    assert cmd.is_file(), f"expected console script after install: {cmd}"
    proc = subprocess.run(
        [str(cmd), "health"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "replayt-mcp-bridge health: ok" in proc.stderr


def test_health_module_nonzero_when_replayt_shadowed(tmp_path: Path) -> None:
    """Prepend a broken ``replayt`` package so ``import replayt`` fails (CI-stable)."""

    overlay = tmp_path / "overlay"
    bad = overlay / "replayt"
    bad.mkdir(parents=True)
    bad.joinpath("__init__.py").write_text(
        'raise ImportError("replayt_mcp_bridge test: shadowed replayt")\n',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = _pythonpath_with_overlay(overlay)
    proc = subprocess.run(
        [sys.executable, "-m", "replayt_mcp_bridge", "health"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 1, proc.stderr + proc.stdout
    assert "replayt import failed" in proc.stderr


def test_health_rejects_extra_arguments() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "replayt_mcp_bridge", "health", "--nope"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "no arguments expected" in proc.stderr
