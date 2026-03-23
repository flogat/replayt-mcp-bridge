"""Contract tests for docs/SECURITY.md and README security discoverability."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SECURITY_PATH = REPO_ROOT / "docs" / "SECURITY.md"
README_PATH = REPO_ROOT / "README.md"
DESIGN_PATH = REPO_ROOT / "docs" / "DESIGN_PRINCIPLES.md"


def test_security_doc_exists() -> None:
    assert SECURITY_PATH.is_file(), "docs/SECURITY.md must exist"


def test_security_doc_lists_environment_variables() -> None:
    text = SECURITY_PATH.read_text(encoding="utf-8")
    assert "## Environment variables" in text
    assert "| Variable | Role |" in text or "| Variable |" in text
    assert "`REPLAYT_LOG_DIR`" in text
    assert "`OPENAI_API_KEY`" in text


def test_security_doc_states_do_not_log_rules() -> None:
    text = SECURITY_PATH.read_text(encoding="utf-8")
    assert "## What must never be logged" in text
    lower = text.lower()
    assert "token" in lower or "credential" in lower
    assert "pii" in lower or "personal" in lower


def test_security_doc_covers_deployment_and_replayt_credentials() -> None:
    text = SECURITY_PATH.read_text(encoding="utf-8")
    assert "## Recommended deployment pattern" in text
    assert "stdio" in text.lower()
    assert "## Interaction with replayt" in text
    assert "auth" in text.lower()


def test_security_doc_notes_mcp_host_logging_risk() -> None:
    text = SECURITY_PATH.read_text(encoding="utf-8")
    assert "## MCP host and client logs" in text
    assert "JSON-RPC" in text or "json-rpc" in text.lower()


def test_readme_links_security_under_clear_heading() -> None:
    text = README_PATH.read_text(encoding="utf-8")
    assert "## Security, secrets, and MCP hosting" in text
    assert "docs/SECURITY.md" in text
    lines = text.splitlines()
    head = "\n".join(lines[:35])
    assert "docs/SECURITY.md" in head


def test_design_principles_points_at_security_doc() -> None:
    text = DESIGN_PATH.read_text(encoding="utf-8")
    assert "SECURITY.md" in text
    assert "trust boundary" in text.lower() or "trust" in text.lower()


def test_bridge_package_does_not_read_process_environ_directly() -> None:
    """Matches docs/SECURITY.md: only observability reads REPLAYT_MCP_BRIDGE_LOG_LEVEL."""
    pkg = REPO_ROOT / "src" / "replayt_mcp_bridge"
    for path in sorted(pkg.rglob("*.py")):
        if path.name == "observability.py":
            continue
        body = path.read_text(encoding="utf-8")
        assert "os.environ" not in body, (
            f"{path.relative_to(REPO_ROOT)} must not use os.environ"
        )
        assert "getenv" not in body, (
            f"{path.relative_to(REPO_ROOT)} must not call getenv"
        )


def test_observability_defines_log_level_env_var() -> None:
    obs = REPO_ROOT / "src" / "replayt_mcp_bridge" / "observability.py"
    text = obs.read_text(encoding="utf-8")
    assert "REPLAYT_MCP_BRIDGE_LOG_LEVEL" in text
