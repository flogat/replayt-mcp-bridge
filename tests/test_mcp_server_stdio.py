"""Smoke tests: MCP stdio server starts without traceback (per docs/MISSION.md)."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


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
