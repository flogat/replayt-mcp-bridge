"""MCP tool bridge for replayt workflow steps."""

from __future__ import annotations

import replayt

__version__ = "0.1.0"


def installed_replayt_version() -> str:
    """Installed replayt version string (PEP 440), for integrators and contract tests."""

    return replayt.__version__


def installed_replayt_version_tuple() -> tuple[int, int, int]:
    """Installed replayt (major, minor, patch); requires replayt >= 0.4.x API."""

    return replayt.__version_tuple__
