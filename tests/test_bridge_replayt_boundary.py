"""Bridge package must exercise the replayt dependency at import/runtime."""

from __future__ import annotations

import replayt
import replayt_mcp_bridge


def test_bridge_reports_installed_replayt_within_declared_range() -> None:
    ver = replayt_mcp_bridge.installed_replayt_version()
    parts = replayt_mcp_bridge.installed_replayt_version_tuple()
    assert ver == replayt.__version__
    assert parts >= (0, 4, 25)
    assert parts < (0, 5, 0)
