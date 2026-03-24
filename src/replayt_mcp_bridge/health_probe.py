"""One-shot install / import probe for operators (``health`` subcommand)."""

from __future__ import annotations

import importlib
import logging
import sys

from replayt_mcp_bridge.observability import configure_bridge_logging, emit_json_log

logger = logging.getLogger("replayt_mcp_bridge")


def run_health_probe() -> int:
    """Run import, version, and logging checks; human-readable status on stderr.

    Returns a process exit code (0 success, 1 on critical probe failure).
    """

    err = sys.stderr
    print("replayt-mcp-bridge health: running install probe", file=err)
    try:
        import replayt_mcp_bridge as bridge_pkg
    except (ImportError, ModuleNotFoundError) as exc:
        print(f"replayt-mcp-bridge health: bridge import failed: {exc}", file=err)
        return 1

    try:
        importlib.import_module("replayt")
    except (ImportError, ModuleNotFoundError) as exc:
        print(f"replayt-mcp-bridge health: replayt import failed: {exc}", file=err)
        return 1

    try:
        from replayt_mcp_bridge import (
            installed_replayt_version,
            installed_replayt_version_tuple,
        )

        v_str = installed_replayt_version()
        major, minor, patch = installed_replayt_version_tuple()
        bridge_version = bridge_pkg.__version__
    except Exception as exc:
        print(
            f"replayt-mcp-bridge health: replayt version resolution failed: {exc}",
            file=err,
        )
        return 1

    try:
        configure_bridge_logging()
    except Exception as exc:
        print(
            f"replayt-mcp-bridge health: logging configuration failed: {exc}", file=err
        )
        return 1

    emit_json_log(
        logger,
        logging.INFO,
        "replayt_mcp_bridge.health.ok",
        replayt_version=v_str,
        replayt_version_tuple={"major": major, "minor": minor, "patch": patch},
        bridge_version=bridge_version,
    )
    print(
        f"replayt-mcp-bridge health: ok (replayt {v_str}, bridge {bridge_version})",
        file=err,
    )
    return 0
