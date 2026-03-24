"""Smoke tests: MCP stdio server starts without traceback (per docs/MISSION.md)."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _console_script_path() -> Path:
    """Resolve the installed console script next to this interpreter.

    Windows venvs place ``python.exe`` and entry-point scripts in the same
    ``Scripts`` directory. A system-wide install keeps ``python.exe`` in the
    prefix root and scripts under ``Scripts\\``.
    """

    name = "replayt-mcp-bridge.exe" if sys.platform == "win32" else "replayt-mcp-bridge"
    exe_dir = Path(sys.executable).resolve().parent
    same_dir = exe_dir / name
    if same_dir.is_file():
        return same_dir
    if sys.platform == "win32":
        under_scripts = exe_dir / "Scripts" / name
        if under_scripts.is_file():
            return under_scripts
    return same_dir


def test_module_invocation_starts_without_traceback() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-m", "replayt_mcp_bridge"],
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.5)
    proc.terminate()
    try:
        out, err = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    combined = (out or "") + (err or "")
    assert "Traceback" not in combined, combined


def test_console_script_starts_without_traceback() -> None:
    cmd = _console_script_path()
    assert cmd.is_file(), f"expected console script after install: {cmd}"
    proc = subprocess.Popen(
        [str(cmd)],
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.5)
    proc.terminate()
    try:
        out, err = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    combined = (out or "") + (err or "")
    assert "Traceback" not in combined, combined
