"""End-to-end MCP stdio session smoke: handshake + one tool call (see docs/MISSION.md).

Uses the official MCP Python SDK client (`stdio_client`, `ClientSession`) against the same
`python -m replayt_mcp_bridge` entrypath as operators. Readiness follows protocol completion
(`initialize`, `tools/list`, `tools/call`), not fixed sleeps.

Happy-path tool: `replayt_version_info` — exercises replayt import and structured success
through FastMCP wiring and JSON-RPC framing.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import TextContent
except ImportError as exc:  # pragma: no cover - optional skip path
    pytest.skip(
        f"MCP Python SDK stdio client tooling unavailable: {exc}",
        allow_module_level=True,
    )

REPO_ROOT = Path(__file__).resolve().parents[1]
# CI-reasonable wall clock; broken stdio or a hung server must not stall the job.
_SESSION_WALL_TIMEOUT_SEC = 45.0


def _structured_or_json_from_tool_result(result: object) -> dict:
    """Normalize MCP `CallToolResult` to a dict (structuredContent or JSON text)."""
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        assert isinstance(structured, dict)
        return structured
    blocks = getattr(result, "content", None) or []
    texts: list[str] = []
    for block in blocks:
        if isinstance(block, TextContent):
            texts.append(block.text)
    assert texts, "tool result had no structuredContent and no text content"
    return json.loads("".join(texts))


async def _stdio_session_replayt_version_info() -> None:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "replayt_mcp_bridge"],
        cwd=str(REPO_ROOT),
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = {t.name for t in listed.tools}
            assert "replayt_version_info" in names, (
                "replayt_version_info missing from tools/list "
                f"(registration or wiring broken); got {sorted(names)}"
            )
            result = await session.call_tool("replayt_version_info", {})
            assert not result.isError, result
            payload = _structured_or_json_from_tool_result(result)
            assert payload.get("status") == "ok", payload
            assert (
                isinstance(payload.get("replayt_version"), str)
                and payload["replayt_version"]
            )


def test_stdio_mcp_session_replayt_version_info() -> None:
    try:
        asyncio.run(
            asyncio.wait_for(
                _stdio_session_replayt_version_info(),
                timeout=_SESSION_WALL_TIMEOUT_SEC,
            )
        )
    except TimeoutError as e:
        raise AssertionError(
            f"MCP stdio session smoke exceeded {_SESSION_WALL_TIMEOUT_SEC}s "
            "(possible hung server or broken transport)"
        ) from e
