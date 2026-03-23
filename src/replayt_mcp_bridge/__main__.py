"""`python -m replayt_mcp_bridge` entrypoint (stdio MCP server)."""

from __future__ import annotations

from replayt_mcp_bridge.server import run_stdio


def main() -> None:
    run_stdio()


if __name__ == "__main__":
    main()
