"""replayt-mcp-bridge - MCP tool bridge for replayt workflow steps."""

from __future__ import annotations

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


def __getattr__(name: str) -> object:
    if name == "run_stdio":
        from .server import run_stdio

        return run_stdio
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
