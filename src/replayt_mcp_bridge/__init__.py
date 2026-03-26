"""replayt-mcp-bridge - MCP tool bridge for replayt workflow steps."""

from __future__ import annotations

from . import observability
from .server import run_stdio

__version__ = "0.1.0"


def installed_replayt_version() -> str:
    """Return the installed replayt version string."""
    try:
        import replayt

        return replayt.__version__
    except ImportError:
        return "unknown"


def installed_replayt_version_tuple() -> tuple[int, int, int]:
    """Return the installed replayt version as a tuple of integers."""
    try:
        import replayt

        return replayt.__version_tuple__
    except ImportError:
        return (0, 0, 0)


__all__ = ["run_stdio", "installed_replayt_version", "installed_replayt_version_tuple"]
