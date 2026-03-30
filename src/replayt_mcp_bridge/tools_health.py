"""Health check tools.

``replayt_doctor`` runs ``python -m replayt doctor`` in a subprocess (argv only, no shell) so the
bridge matches the Typer CLI without a stable ``replayt`` public Python entry for doctor on
``>=0.4.25,<0.5``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import typer
from mcp.server.fastmcp import Context
from replayt.cli.targets import load_target

from . import installed_replayt_version, installed_replayt_version_tuple
from .mcp_instance import mcp
from .tools_bounds import (
    EchoMessageStr,
    InputOverridesOpt,
    JsonBlobStrOpt,
    TierAStringOpt,
)
from .tools_common import _log_replayt_tool_boundaries, _tool_error
from .utils import with_timeout

_TOOL = "replayt_doctor"
_SURFACE_SUBPROC = "replayt doctor (subprocess / parse)"
_SURFACE_TARGET = "replayt doctor + replayt.cli.targets.load_target"


async def _run_replayt_doctor_subprocess(argv: list[str]) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    return proc.returncode, stdout_b, stderr_b


def _build_doctor_argv(
    *,
    skip_connectivity: bool,
    target: str | None,
    strict_graph: bool,
    inputs_json: str | None,
    inputs_file: str | None,
    input_overrides: list[str] | None,
) -> list[str]:
    argv: list[str] = [sys.executable, "-m", "replayt", "doctor", "--format", "json"]
    if skip_connectivity:
        argv.append("--skip-connectivity")
    if target:
        argv.extend(["--target", target])
    if strict_graph and target:
        argv.append("--strict-graph")
    if inputs_json is not None:
        argv.extend(["--inputs-json", inputs_json])
    if inputs_file and inputs_file.strip():
        argv.extend(["--inputs-file", str(Path(inputs_file).expanduser())])
    if input_overrides:
        for pair in input_overrides:
            if pair and str(pair).strip():
                argv.extend(["--input", str(pair)])
    return argv


def _parse_doctor_json(stdout_b: bytes) -> dict[str, Any] | None:
    text = stdout_b.decode(errors="replace").strip()
    if not text:
        return None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(doc, dict):
        return None
    schema = doc.get("schema")
    if not isinstance(schema, str) or "doctor" not in schema.lower():
        return None
    return doc


@mcp.tool()
@_log_replayt_tool_boundaries
def replayt_echo(message: EchoMessageStr) -> dict[str, str]:
    """Echo a message back to the client."""
    return {"status": "ok", "echo": message}


@mcp.tool()
@_log_replayt_tool_boundaries
def replayt_version_info() -> dict[str, Any]:
    """Return the installed replayt version."""
    major, minor, patch = installed_replayt_version_tuple()
    return {
        "status": "ok",
        "replayt_version": installed_replayt_version(),
        "replayt_version_tuple": {"major": major, "minor": minor, "patch": patch},
    }


@mcp.tool()
@_log_replayt_tool_boundaries
async def replayt_doctor(
    skip_connectivity: bool = True,
    target: TierAStringOpt = None,
    strict_graph: bool = False,
    inputs_json: JsonBlobStrOpt = None,
    inputs_file: TierAStringOpt = None,
    input_overrides: InputOverridesOpt = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Run ``replayt doctor`` and return the JSON report (default skips connectivity probes)."""

    return await with_timeout(_replayt_doctor_impl, _TOOL)(
        skip_connectivity,
        target,
        strict_graph,
        inputs_json,
        inputs_file,
        input_overrides,
        ctx,
    )


async def _replayt_doctor_impl(
    skip_connectivity: bool,
    target: str | None,
    strict_graph: bool,
    inputs_json: str | None,
    inputs_file: str | None,
    input_overrides: list[str] | None,
    ctx: Context | None,
) -> dict[str, Any]:
    del ctx  # FastMCP injects; subprocess does not need it.

    tgt = target.strip() if isinstance(target, str) else None
    if not tgt:
        tgt = None

    if tgt is not None:
        try:
            load_target(tgt)
        except typer.BadParameter as exc:
            return _tool_error(
                tool=_TOOL,
                replayt_surface=_SURFACE_TARGET,
                message=str(exc),
            )

    argv = _build_doctor_argv(
        skip_connectivity=skip_connectivity,
        target=tgt,
        strict_graph=strict_graph,
        inputs_json=inputs_json,
        inputs_file=inputs_file,
        input_overrides=input_overrides,
    )

    try:
        code, out_b, err_b = await _run_replayt_doctor_subprocess(argv)
    except OSError as exc:
        return _tool_error(
            tool=_TOOL,
            replayt_surface=_SURFACE_SUBPROC,
            message=f"Failed to start replayt doctor subprocess: {exc}",
        )

    doctor = _parse_doctor_json(out_b)
    if doctor is None:
        err_hint = err_b.decode(errors="replace").strip()
        if len(err_hint) > 400:
            err_hint = err_hint[:400] + "…"
        msg = "replayt doctor did not print a parseable JSON doctor report on stdout"
        if err_hint:
            msg = f"{msg} (stderr: {err_hint})"
        return _tool_error(
            tool=_TOOL,
            replayt_surface=_SURFACE_SUBPROC,
            message=msg,
        )

    return {
        "status": "ok",
        "tool": _TOOL,
        "doctor": doctor,
        "replayt_exit_code": int(code),
    }
