"""`python -m replayt_mcp_bridge` entrypoint (stdio MCP server or ``health`` probe)."""

from __future__ import annotations

import sys


def main() -> None:
    argv = sys.argv[1:]
    if argv:
        sub = argv[0]
        if sub == "health":
            extra = argv[1:]
            if extra:
                print(
                    "replayt-mcp-bridge: no arguments expected after 'health'",
                    file=sys.stderr,
                )
                sys.exit(2)
            from replayt_mcp_bridge.health_probe import run_health_probe

            sys.exit(run_health_probe())
        print(
            f"replayt-mcp-bridge: unknown command {sub!r} "
            "(expected no arguments for the MCP server, or 'health')",
            file=sys.stderr,
        )
        sys.exit(2)

    from replayt_mcp_bridge.server import run_stdio

    run_stdio()


if __name__ == "__main__":
    main()
