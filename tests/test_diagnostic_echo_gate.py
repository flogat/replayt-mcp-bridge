"""MCP diagnostic echo gate: tools/list + tools/call (see docs/MCP_TOOLS.md)."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import TextContent
except ImportError as exc:  # pragma: no cover
    pytest.skip(
        f"MCP Python SDK stdio client tooling unavailable: {exc}",
        allow_module_level=True,
    )

REPO_ROOT = Path(__file__).resolve().parents[1]
_SESSION_WALL_TIMEOUT_SEC = 45.0


def _structured_or_json_from_tool_result(result: object) -> dict:
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


async def _stdio_echo_session(
    *,
    module_args: list[str],
    extra_env: dict[str, str] | None,
    expect_echo_listed: bool,
    expect_call_error: bool,
) -> None:
    env = {**dict(os.environ), **(extra_env or {})}
    server = StdioServerParameters(
        command=sys.executable,
        args=module_args,
        cwd=str(REPO_ROOT),
        env=env,
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = {t.name for t in listed.tools}
            assert ("replayt_echo" in names) == expect_echo_listed, sorted(names)
            result = await session.call_tool(
                "replayt_echo", {"message": "secret-probe"}
            )
            payload = _structured_or_json_from_tool_result(result)
            if expect_call_error:
                assert result.isError or payload.get("status") == "error", payload
                assert payload.get("tool") == "replayt_echo"
                assert (
                    payload.get("replayt_surface") == "bridge_diagnostic_tools_disabled"
                )
                assert payload.get("correlation_id")
                assert "secret-probe" not in json.dumps(payload)
                assert payload.get("status") == "error"
            else:
                assert not result.isError, payload
                assert payload.get("status") == "ok"
                assert payload.get("echo") == "secret-probe"


def test_stdio_diagnostic_echo_gate_off_lists_and_echoes() -> None:
    asyncio.run(
        asyncio.wait_for(
            _stdio_echo_session(
                module_args=["-m", "replayt_mcp_bridge"],
                extra_env=None,
                expect_echo_listed=True,
                expect_call_error=False,
            ),
            timeout=_SESSION_WALL_TIMEOUT_SEC,
        )
    )


def test_stdio_diagnostic_echo_gate_on_omits_and_errors() -> None:
    asyncio.run(
        asyncio.wait_for(
            _stdio_echo_session(
                module_args=["-m", "replayt_mcp_bridge"],
                extra_env={"REPLAYT_MCP_BRIDGE_DISABLE_DIAGNOSTIC_ECHO_TOOLS": "1"},
                expect_echo_listed=False,
                expect_call_error=True,
            ),
            timeout=_SESSION_WALL_TIMEOUT_SEC,
        )
    )


def test_stdio_diagnostic_echo_cli_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(
        "REPLAYT_MCP_BRIDGE_DISABLE_DIAGNOSTIC_ECHO_TOOLS", raising=False
    )
    asyncio.run(
        asyncio.wait_for(
            _stdio_echo_session(
                module_args=["-m", "replayt_mcp_bridge", "--no-diagnostic-echo-tools"],
                extra_env=None,
                expect_echo_listed=False,
                expect_call_error=True,
            ),
            timeout=_SESSION_WALL_TIMEOUT_SEC,
        )
    )


def test_health_subprocess_rejects_combined_no_diagnostic_flag() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "replayt_mcp_bridge",
            "--no-diagnostic-echo-tools",
            "health",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "not valid" in proc.stderr.lower() or "health" in proc.stderr.lower()
