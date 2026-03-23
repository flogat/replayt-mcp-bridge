"""Minimal MCP server (stdio) for replayt-mcp-bridge."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("replayt-mcp-bridge")


@mcp.tool()
def ping() -> str:
    """Stub health check; real replayt-backed tools will be added incrementally."""

    return "pong"


def run_stdio() -> None:
    """Run the MCP server on stdin/stdout (JSON-RPC per MCP)."""

    mcp.run(transport="stdio")
