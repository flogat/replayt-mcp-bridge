"""Contract tests for docs/MCP_HOST_CONFIG.md discoverability and required content."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_HOST_CONFIG_PATH = REPO_ROOT / "docs" / "MCP_HOST_CONFIG.md"
README_PATH = REPO_ROOT / "README.md"


def test_mcp_host_config_doc_exists() -> None:
    assert MCP_HOST_CONFIG_PATH.is_file(), "docs/MCP_HOST_CONFIG.md must exist"


def test_mcp_host_config_doc_covers_entrypoints_and_security() -> None:
    text = MCP_HOST_CONFIG_PATH.read_text(encoding="utf-8")
    assert "`replayt-mcp-bridge`" in text
    assert "replayt_mcp_bridge" in text
    assert "python -m" in text or "`-m`" in text
    assert "[SECURITY.md](SECURITY.md)" in text
    assert "mcpServers" in text


def test_readme_links_mcp_host_config_near_quick_start() -> None:
    text = README_PATH.read_text(encoding="utf-8")
    assert "docs/MCP_HOST_CONFIG.md" in text
    assert "**MCP hosts:**" in text
