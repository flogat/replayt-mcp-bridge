"""Tests for structured logging and redaction helpers."""

from __future__ import annotations

import json
import logging

import pytest

from replayt_mcp_bridge.observability import emit_json_log, redact_structure


def test_redact_structure_masks_dummy_token_value() -> None:
    secret = "dummy_token_replayt_mcp_bridge_redaction_test_9f2c"
    redacted = redact_structure({"oauth_token": secret, "ok": True})
    assert redacted["oauth_token"] == "[REDACTED]"
    assert redacted["ok"] is True
    assert secret not in json.dumps(redacted)


def test_emit_json_log_redacts_sensitive_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "dummy_token_emit_json_log_test_4b1e"
    log = logging.getLogger("replayt_mcp_bridge.test_emit")
    caplog.set_level(logging.INFO, logger="replayt_mcp_bridge.test_emit")
    emit_json_log(
        log, logging.INFO, "replayt_mcp_bridge.test.redaction", tool="t", token=secret
    )
    blob = caplog.text
    assert secret not in blob
    assert "[REDACTED]" in blob
