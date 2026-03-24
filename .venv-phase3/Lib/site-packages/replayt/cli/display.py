"""Event summaries, replay HTML/text, filters, and time parsing for CLI commands."""

from __future__ import annotations

import html
import json
import re
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import typer

REPLAY_HTML_CSS = """
body{background:#f8fafc;color:#0f172a;font-family:ui-sans-serif,system-ui,sans-serif;margin:0;padding:24px}
main{max-width:56rem;margin:0 auto}
.title{font-size:1.5rem;font-weight:600;margin:0 0 .5rem}
.sub{font-size:.875rem;color:#475569;margin:0 0 1rem}
.card{
  background:#fff;
  border:1px solid #e2e8f0;
  border-radius:.5rem;
  box-shadow:0 1px 2px rgba(15,23,42,.08);
  padding:1rem
}
.row{
  font-family:ui-monospace,SFMono-Regular,monospace;
  font-size:.875rem;
  white-space:pre-wrap;
  border-bottom:1px solid #e2e8f0;
  padding:.25rem 0
}
.foot{font-size:.75rem;color:#64748b;margin-top:1rem}
.rp-att{font-size:.875rem;margin:.5rem 0 1rem;padding:.75rem 1rem;background:#fef9c3;
  border-radius:.375rem;border:1px solid #fde047}
.rp-att-label{font-weight:600;color:#713f12;margin-right:.35rem}
.rp-att-code{font-family:ui-monospace,SFMono-Regular,monospace;color:#422006;font-size:.875rem}
.rp-muted-note{font-size:.8125rem;color:#64748b;margin:0 0 .75rem}
.rp-section{margin:1.25rem 0}
.rp-h2{font-size:1.125rem;font-weight:600;margin:0 0 .75rem;color:#0f172a}
.rp-card{
  background:#fff;border:1px solid #e2e8f0;border-radius:.5rem;
  box-shadow:0 1px 2px rgba(15,23,42,.08);padding:1rem
}
.rp-card-tight p{margin:.15rem 0;font-size:.875rem}
.rp-muted{color:#64748b;font-size:.8125rem;margin:0 0 .75rem}
.rp-label{font-weight:500;color:#64748b}
.rp-handoff-row{margin:.65rem 0}
.rp-code{font-family:ui-monospace,SFMono-Regular,monospace;color:#0f172a;font-size:.875rem}
"""


def jsonl_type_str(typ: Any) -> str | None:
    """Return *typ* when it is a string (normal JSONL ``type`` field), else ``None``.

    Well-formed replayt logs always use string event types. Hand-edited or hostile JSONL may
    use other JSON types; using such values in ``value in frozenset`` or ``value in {...}``
    can raise ``TypeError`` (unhashable types).
    """

    return typ if isinstance(typ, str) else None


def event_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "status": "unknown",
        "workflow_name": None,
        "workflow_version": None,
        "workflow_contract_sha256": None,
        "state_count": 0,
        "transition_count": 0,
        "llm_calls": 0,
        "tool_calls": 0,
        "notes": 0,
        "approvals": 0,
        "last_ts": None,
        "tags": {},
        "run_metadata": {},
        "experiment": {},
    }
    for event in events:
        summary["last_ts"] = event.get("ts")
        typ = event.get("type")
        payload = event.get("payload") or {}
        if typ == "run_started":
            summary["workflow_name"] = payload.get("workflow_name")
            summary["workflow_version"] = payload.get("workflow_version")
            summary["tags"] = payload.get("tags") or {}
            summary["run_metadata"] = payload.get("run_metadata") or {}
            runtime = payload.get("runtime") or {}
            workflow_runtime = runtime.get("workflow") if isinstance(runtime, dict) else {}
            if isinstance(workflow_runtime, dict):
                digest = workflow_runtime.get("contract_sha256")
                if isinstance(digest, str) and digest:
                    summary["workflow_contract_sha256"] = digest
            exp = payload.get("experiment")
            summary["experiment"] = exp if isinstance(exp, dict) else {}
        elif typ == "state_entered":
            summary["state_count"] += 1
        elif typ == "transition":
            summary["transition_count"] += 1
        elif typ == "llm_request":
            summary["llm_calls"] += 1
        elif typ == "tool_call":
            summary["tool_calls"] += 1
        elif typ == "step_note":
            summary["notes"] += 1
        elif typ == "approval_requested":
            summary["approvals"] += 1
        elif typ == "run_completed":
            summary["status"] = payload.get("status", summary["status"])
        elif typ == "run_paused":
            summary["status"] = "paused"
    return summary


def _inline_error_message(error: Any) -> str:
    if isinstance(error, dict):
        err_type = str(error.get("type") or "").strip()
        err_message = str(error.get("message") or "").strip()
        if err_type and err_message:
            return f"{err_type}: {err_message}"
        return err_type or err_message
    if error is None:
        return ""
    return str(error).strip()


def _truncate_inline(text: str, *, limit: int = 120) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def run_attention_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize the current stakeholder-facing action on a run for ``replayt runs``."""

    summary = event_summary(events)
    approvals: list[dict[str, Any]] = []
    pending_by_id: dict[str, deque[int]] = defaultdict(deque)
    latest_failure: dict[str, Any] | None = None
    latest_structured_output_failure: dict[str, Any] | None = None
    latest_run_paused: dict[str, Any] | None = None

    for event in events:
        ts = event.get("ts")
        typ = event.get("type")
        payload = event.get("payload") or {}

        if typ == "approval_requested":
            approval_id = payload.get("approval_id")
            if approval_id is None:
                continue
            approvals.append(
                {
                    "approval_id": str(approval_id),
                    "state": payload.get("state"),
                    "summary": payload.get("summary"),
                    "requested_ts": ts,
                    "approved": None,
                }
            )
            pending_by_id[str(approval_id)].append(len(approvals) - 1)
        elif typ == "approval_resolved":
            approval_id = payload.get("approval_id")
            if approval_id is None:
                continue
            pending = pending_by_id.get(str(approval_id))
            if pending:
                approvals[pending.popleft()]["approved"] = bool(payload.get("approved"))
        elif typ == "run_failed":
            latest_failure = {
                "state": payload.get("state"),
                "error": payload.get("error"),
                "ts": ts,
            }
        elif typ == "structured_output_failed":
            latest_structured_output_failure = {
                "state": payload.get("state"),
                "schema_name": payload.get("schema_name"),
                "stage": payload.get("stage"),
                "error": payload.get("error"),
                "ts": ts,
            }
        elif typ == "run_paused":
            latest_run_paused = {
                "approval_id": payload.get("approval_id"),
                "reason": payload.get("reason"),
                "ts": ts,
            }

    pending_approvals = [
        {
            "approval_id": approval.get("approval_id"),
            "state": approval.get("state"),
            "summary": approval.get("summary"),
            "requested_ts": approval.get("requested_ts"),
        }
        for approval in approvals
        if approval.get("approved") is None
    ]
    if not pending_approvals and summary.get("status") == "paused" and latest_run_paused is not None:
        paused_approval_id = latest_run_paused.get("approval_id")
        if paused_approval_id not in (None, ""):
            pending_approvals.append(
                {
                    "approval_id": str(paused_approval_id),
                    "state": None,
                    "summary": None,
                    "requested_ts": latest_run_paused.get("ts"),
                }
            )

    attention_kind = "none"
    attention_summary = ""
    status = str(summary.get("status") or "unknown")
    if status == "paused":
        attention_kind = "pending_approval"
        if len(pending_approvals) == 1:
            approval = pending_approvals[0]
            attention_summary = f"awaiting approval {approval.get('approval_id') or 'approval'}"
            state = approval.get("state")
            if state not in (None, ""):
                attention_summary += f" @ {state}"
        elif len(pending_approvals) > 1:
            attention_summary = f"awaiting {len(pending_approvals)} approvals"
        else:
            pause_reason = str(latest_run_paused.get("reason") or "").strip() if latest_run_paused else ""
            attention_summary = f"paused: {pause_reason}" if pause_reason else "paused"
    elif status == "failed":
        if latest_failure is not None:
            attention_kind = "run_failed"
            state = str(latest_failure.get("state") or "").strip()
            err = _inline_error_message(latest_failure.get("error"))
            if state and err:
                attention_summary = f"failed in {state}: {err}"
            elif state:
                attention_summary = f"failed in {state}"
            elif err:
                attention_summary = f"failed: {err}"
            else:
                attention_summary = "failed"
        elif latest_structured_output_failure is not None:
            attention_kind = "structured_output_failed"
            schema_name = str(latest_structured_output_failure.get("schema_name") or "").strip()
            stage = str(latest_structured_output_failure.get("stage") or "").strip()
            if schema_name and stage:
                attention_summary = f"parse failure {schema_name} ({stage})"
            elif schema_name:
                attention_summary = f"parse failure {schema_name}"
            else:
                attention_summary = "failed"

    return {
        "attention_kind": attention_kind,
        "attention_summary": _truncate_inline(attention_summary) if attention_summary else "",
        "pending_approvals": pending_approvals,
        "latest_failure": latest_failure,
        "latest_structured_output_failure": latest_structured_output_failure,
    }


def _md_inline_code(text: str) -> str:
    safe = str(text).replace("`", "'")
    return f"`{safe}`"


def _stakeholder_paused_resume_rows(
    run_id: str,
    summary: dict[str, Any],
    attention: dict[str, Any],
) -> list[tuple[str, str]]:
    """Label + command for ``replayt resume`` after approval (inspect + report handoff)."""

    status = str(summary.get("status") or "")
    if status != "paused":
        return []
    pending = attention.get("pending_approvals") or []
    target_note = "Replace TARGET with your MODULE:wf or workflow path."
    if len(pending) == 1:
        aid = pending[0].get("approval_id")
        if aid not in (None, ""):
            return [
                (
                    "Resume after approval",
                    f"replayt resume TARGET {run_id} --approval {aid}  # {target_note}",
                )
            ]
        return [
            (
                "Resume after approval",
                f"replayt resume TARGET {run_id} --approval <approval_id>  # {target_note}",
            )
        ]
    if len(pending) > 1:
        ids = [
            str(p.get("approval_id") or "").strip()
            for p in pending
            if str(p.get("approval_id") or "").strip()
        ]
        if ids:
            pending_note = "pending approval ids: " + ", ".join(ids)
            return [
                (
                    "Resume after approvals",
                    f"replayt resume TARGET {run_id} --approval <approval_id>  # {target_note} {pending_note}",
                )
            ]
        return [
            (
                "Resume after approvals",
                f"replayt resume TARGET {run_id} --approval <approval_id>  # {target_note}",
            )
        ]
    return [
        (
            "Resume after approval",
            f"replayt resume TARGET {run_id} --approval <approval_id>  # {target_note} "
            f"See replayt inspect {run_id} --output json for details.",
        )
    ]


def _stakeholder_report_handoff_rows(
    run_id: str,
    events: list[dict[str, Any]],
    *,
    report_style: Literal["stakeholder", "support"] = "stakeholder",
) -> list[tuple[str, str]]:
    """Ordered (label, command) lines for stakeholder/support report handoff panels."""

    summary = event_summary(events)
    attention = run_attention_summary(events)
    status = str(summary.get("status") or "")
    bundle_infix = "support" if report_style == "support" else "stakeholder"
    regen_md_lbl = (
        "Regenerate support report (Markdown)"
        if report_style == "support"
        else "Regenerate stakeholder report (Markdown)"
    )
    regen_html_lbl = (
        "Regenerate support report (HTML)"
        if report_style == "support"
        else "Regenerate stakeholder report (HTML)"
    )
    bundle_lbl = "Support bundle (.tar.gz)" if report_style == "support" else "Stakeholder bundle (.tar.gz)"
    rows: list[tuple[str, str]] = [
        (
            "Inspect (paste-friendly summary)",
            f"replayt inspect {run_id} --output markdown --style {report_style}",
        ),
        (
            regen_md_lbl,
            f"replayt report {run_id} --format markdown --style {report_style}",
        ),
        (
            regen_html_lbl,
            f"replayt report {run_id} --format html --style {report_style} --out report.html",
        ),
        (
            "Offline timeline HTML",
            f"replayt replay {run_id} --format html --style {report_style} --out run.html",
        ),
        (
            bundle_lbl,
            f"replayt bundle-export {run_id} --out {run_id}-{bundle_infix}-bundle.tar.gz "
            f"--report-style {report_style}",
        ),
    ]
    if status == "failed":
        rows.append(("Inspect (JSON for engineers)", f"replayt inspect {run_id} --output json"))
    rows.extend(_stakeholder_paused_resume_rows(run_id, summary, attention))
    return rows


def stakeholder_report_handoff_markdown(
    run_id: str,
    events: list[dict[str, Any]],
    *,
    report_style: Literal["stakeholder", "support"] = "stakeholder",
) -> str:
    """Markdown section with copy-paste CLI commands for stakeholder/support HTML and Markdown reports."""

    lines: list[str] = [
        "## Stakeholder CLI handoff",
        "",
        "Copy-paste commands for operators. Repeat `--log-dir`, `--log-subdir`, or `--sqlite` on each command "
        "when you are not using the default log store.",
        "",
    ]
    for label, cmd in _stakeholder_report_handoff_rows(run_id, events, report_style=report_style):
        safe_cmd = cmd.replace("`", "'")
        lines.append(f"- **{label}:** `{safe_cmd}`")
    return "\n".join(lines) + "\n"


def stakeholder_report_handoff_html(
    run_id: str,
    events: list[dict[str, Any]],
    *,
    report_style: Literal["stakeholder", "support"] = "stakeholder",
) -> str:
    """HTML fragment (section) matching :func:`stakeholder_report_handoff_markdown`."""

    intro = (
        "Copy-paste commands for operators. Repeat --log-dir, --log-subdir, or --sqlite on each command "
        "when you are not using the default log store."
    )
    row_html: list[str] = [f'        <p class="rp-muted">{html.escape(intro)}</p>']
    for label, cmd in _stakeholder_report_handoff_rows(run_id, events, report_style=report_style):
        row_html.append(
            '        <p class="rp-handoff-row">'
            f'<span class="rp-label">{html.escape(label)}</span><br/>'
            '<code class="rp-code rp-pre" style="display:block;margin-top:0.35rem;white-space:pre-wrap;">'
            f"{html.escape(cmd)}"
            "</code></p>"
        )
    inner = "\n".join(row_html)
    return (
        '    <section class="rp-section">\n'
        '      <h2 class="rp-h2">Stakeholder CLI handoff</h2>\n'
        '      <div class="rp-card rp-card-tight">\n'
        f"{inner}\n"
        "      </div>\n"
        "    </section>\n"
    )


def _llm_model_cli_suffix(llm_model_filter: frozenset[str] | None) -> str:
    """Space-prefixed repeatable ``--llm-model`` flags for copy-paste handoff lines."""

    if not llm_model_filter:
        return ""
    return "".join(f" --llm-model {m}" for m in sorted(llm_model_filter))


def _stakeholder_report_diff_handoff_rows(
    run_a: str,
    run_b: str,
    events_a: list[dict[str, Any]],
    events_b: list[dict[str, Any]],
    *,
    style: Literal["stakeholder", "support"],
    llm_model_filter: frozenset[str] | None = None,
) -> list[tuple[str, str]]:
    """Ordered (label, command) lines for stakeholder/support ``replayt report-diff`` handoff panels."""

    suf = _llm_model_cli_suffix(llm_model_filter)
    bundle_infix = "support" if style == "support" else "stakeholder"
    report_lbl = "Support report" if style == "support" else "Stakeholder report"
    bundle_lbl = "Support bundle" if style == "support" else "Stakeholder bundle"
    rows: list[tuple[str, str]] = [
        (
            "Regenerate this comparison (Markdown)",
            f"replayt report-diff {run_a} {run_b} --format markdown --style {style}{suf}",
        ),
        (
            "Regenerate this comparison (HTML)",
            f"replayt report-diff {run_a} {run_b} --format html --style {style} --out report-diff.html{suf}",
        ),
        (
            "Machine-readable diff (JSON)",
            f"replayt diff {run_a} {run_b} --output json{suf}",
        ),
        (
            "Inspect run A (paste-friendly)",
            f"replayt inspect {run_a} --output markdown --style {style}",
        ),
        (
            "Inspect run B (paste-friendly)",
            f"replayt inspect {run_b} --output markdown --style {style}",
        ),
        (
            f"{report_lbl} (run A, Markdown)",
            f"replayt report {run_a} --format markdown --style {style}{suf}",
        ),
        (
            f"{report_lbl} (run B, Markdown)",
            f"replayt report {run_b} --format markdown --style {style}{suf}",
        ),
        (
            "Offline timeline HTML (run A)",
            f"replayt replay {run_a} --format html --style {style} --out run-a.html{suf}",
        ),
        (
            "Offline timeline HTML (run B)",
            f"replayt replay {run_b} --format html --style {style} --out run-b.html{suf}",
        ),
        (
            f"{bundle_lbl} (run A)",
            f"replayt bundle-export {run_a} --out {run_a}-{bundle_infix}-bundle.tar.gz --report-style {style}",
        ),
        (
            f"{bundle_lbl} (run B)",
            f"replayt bundle-export {run_b} --out {run_b}-{bundle_infix}-bundle.tar.gz --report-style {style}",
        ),
    ]
    sum_a = event_summary(events_a)
    sum_b = event_summary(events_b)
    att_a = run_attention_summary(events_a)
    att_b = run_attention_summary(events_b)
    if str(sum_a.get("status") or "") == "failed":
        rows.append(
            ("Inspect run A (JSON for engineers)", f"replayt inspect {run_a} --output json{suf}"),
        )
    if str(sum_b.get("status") or "") == "failed":
        rows.append(
            ("Inspect run B (JSON for engineers)", f"replayt inspect {run_b} --output json{suf}"),
        )
    for label, cmd in _stakeholder_paused_resume_rows(run_a, sum_a, att_a):
        rows.append((f"Run A — {label}", cmd))
    for label, cmd in _stakeholder_paused_resume_rows(run_b, sum_b, att_b):
        rows.append((f"Run B — {label}", cmd))
    return rows


def stakeholder_report_diff_handoff_markdown(
    run_a: str,
    run_b: str,
    events_a: list[dict[str, Any]],
    events_b: list[dict[str, Any]],
    *,
    style: Literal["stakeholder", "support"],
    llm_model_filter: frozenset[str] | None = None,
) -> str:
    """Markdown section with copy-paste CLI commands for two-run comparison handoffs."""

    lines: list[str] = [
        "## Stakeholder CLI handoff",
        "",
        "Copy-paste commands for operators. Repeat `--log-dir`, `--log-subdir`, or `--sqlite` on each command "
        "when you are not using the default log store.",
        "",
    ]
    for label, cmd in _stakeholder_report_diff_handoff_rows(
        run_a,
        run_b,
        events_a,
        events_b,
        style=style,
        llm_model_filter=llm_model_filter,
    ):
        safe_cmd = cmd.replace("`", "'")
        lines.append(f"- **{label}:** `{safe_cmd}`")
    return "\n".join(lines) + "\n"


def stakeholder_report_diff_handoff_html(
    run_a: str,
    run_b: str,
    events_a: list[dict[str, Any]],
    events_b: list[dict[str, Any]],
    *,
    style: Literal["stakeholder", "support"],
    llm_model_filter: frozenset[str] | None = None,
) -> str:
    """HTML fragment (section) matching :func:`stakeholder_report_diff_handoff_markdown`."""

    intro = (
        "Copy-paste commands for operators. Repeat --log-dir, --log-subdir, or --sqlite on each command "
        "when you are not using the default log store."
    )
    row_html: list[str] = [f'        <p class="rp-muted">{html.escape(intro)}</p>']
    for label, cmd in _stakeholder_report_diff_handoff_rows(
        run_a,
        run_b,
        events_a,
        events_b,
        style=style,
        llm_model_filter=llm_model_filter,
    ):
        row_html.append(
            '        <p class="rp-handoff-row">'
            f'<span class="rp-label">{html.escape(label)}</span><br/>'
            '<code class="rp-code rp-pre" style="display:block;margin-top:0.35rem;white-space:pre-wrap;">'
            f"{html.escape(cmd)}"
            "</code></p>"
        )
    inner = "\n".join(row_html)
    return (
        '    <section class="rp-section">\n'
        '      <h2 class="rp-h2">Stakeholder CLI handoff</h2>\n'
        '      <div class="rp-card rp-card-tight">\n'
        f"{inner}\n"
        "      </div>\n"
        "    </section>\n"
    )


def _stakeholder_paused_resume_md_bullets(
    run_id: str,
    summary: dict[str, Any],
    attention: dict[str, Any],
) -> list[str]:
    """Markdown bullets for ``replayt resume`` (inspect suggested next steps; prose matches prior CLI copy)."""

    lines: list[str] = []
    for label, cmd in _stakeholder_paused_resume_rows(run_id, summary, attention):
        cmd_base = cmd.split("  # ", 1)[0].strip()
        if label == "Resume after approval" and "See replayt inspect" in cmd:
            lines.append(
                f"- After approval: `replayt resume TARGET {run_id} --approval <approval_id>` "
                f"(replace `TARGET`; see `replayt inspect {run_id} --output json` for details)."
            )
            continue
        if label == "Resume after approval":
            lines.append(
                f"- After approval: `{cmd_base}` (replace `TARGET` with your `MODULE:wf` or workflow path)."
            )
        elif label == "Resume after approvals":
            pending = attention.get("pending_approvals") or []
            ids = [
                str(p.get("approval_id") or "").strip()
                for p in pending
                if str(p.get("approval_id") or "").strip()
            ]
            if ids:
                quoted = ", ".join(_md_inline_code(i) for i in ids)
                lines.append(
                    f"- After approvals: `{cmd_base}` (replace `TARGET`; pending ids: {quoted})."
                )
            else:
                lines.append(
                    f"- After approvals: `{cmd_base}` "
                    "(replace `TARGET` with your `MODULE:wf` or workflow path)."
                )
    return lines


def inspect_stakeholder_markdown(
    run_id: str,
    events: list[dict[str, Any]],
    *,
    style: Literal["stakeholder", "support"] = "stakeholder",
) -> str:
    """Short Markdown blurb for PM/support paste (full run; not filtered event lists)."""

    summary = event_summary(events)
    attention = run_attention_summary(events)
    if style == "support":
        lines: list[str] = [f"## Support handoff — `{run_id}`", ""]
    else:
        lines = [f"## replayt run `{run_id}`", ""]
    wf = f"{summary.get('workflow_name')}@{summary.get('workflow_version')}"
    lines.append(f"- **Workflow:** {_md_inline_code(wf)}")
    lines.append(f"- **Status:** {_md_inline_code(str(summary.get('status') or 'unknown'))}")
    contract_sha256 = summary.get("workflow_contract_sha256")
    if isinstance(contract_sha256, str) and contract_sha256.strip():
        lines.append(f"- **Contract digest:** `{contract_sha256.strip()}`")
    last_ts = summary.get("last_ts")
    if last_ts not in (None, ""):
        lines.append(f"- **Last event time:** {_md_inline_code(str(last_ts))}")
    kind = str(attention.get("attention_kind") or "none")
    asum = str(attention.get("attention_summary") or "").strip()
    if kind != "none" and asum:
        lines.append(f"- **Needs attention:** {_md_inline_code(asum)}")
    elif kind != "none":
        lines.append(f"- **Needs attention:** {_md_inline_code(kind)}")
    lines.extend(["", "### Suggested next steps", ""])
    if style == "support":
        lines.append(
            f"- Support-oriented report (Markdown): `replayt report {run_id} --format markdown --style support` "
            "(repeat `--log-dir`, `--log-subdir`, or `--sqlite` if you used them here)."
        )
        lines.append(
            f"- Offline timeline HTML (failure/approval-first; omits tool/LLM rows like support reports): "
            f"`replayt replay {run_id} --format html --style support --out run.html` "
            "(same log flags as above)."
        )
        lines.append(
            f"- Support archive bundle (HTML report + timeline + sanitized JSONL + manifest): "
            f"`replayt bundle-export {run_id} --out {run_id}-support-bundle.tar.gz --report-style support` "
            "(add `--target MODULE:wf` when you need `workflow.contract.json` / `workflow.mmd.txt` in the tarball; "
            "same log flags as above)."
        )
    else:
        lines.append(
            f"- Stakeholder-facing report: `replayt report {run_id} --format markdown --style stakeholder` "
            "(repeat `--log-dir`, `--log-subdir`, or `--sqlite` if you used them here)."
        )
        lines.append(
            f"- Offline timeline HTML (same omissions as stakeholder report tool sections): "
            f"`replayt replay {run_id} --format html --style stakeholder --out run.html` "
            "(same log flags as above)."
        )
        lines.append(
            f"- Stakeholder archive (HTML report + timeline + sanitized JSONL + manifest): "
            f"`replayt bundle-export {run_id} --out {run_id}-stakeholder-bundle.tar.gz --report-style stakeholder` "
            "(add `--target MODULE:wf` when you need `workflow.contract.json` / `workflow.mmd.txt` in the tarball; "
            "same log flags as above)."
        )
    lines.extend(_stakeholder_paused_resume_md_bullets(run_id, summary, attention))
    return "\n".join(lines) + "\n"


def _runs_inventory_md_cell(val: Any, *, max_len: int = 96) -> str:
    """Escape a value for a GitHub-flavored Markdown table cell."""

    s = "" if val in (None, "") else str(val)
    s = s.replace("|", "\\|").replace("\n", " ").strip()
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def _runs_inventory_handoff_rows(style: Literal["stakeholder", "support"]) -> list[tuple[str, str]]:
    """Copy-paste command rows for run-inventory Markdown; use literal ``RUN_ID`` placeholder."""

    bundle_infix = "support" if style == "support" else "stakeholder"
    regen_md_lbl = (
        "Regenerate support report (Markdown)"
        if style == "support"
        else "Regenerate stakeholder report (Markdown)"
    )
    regen_html_lbl = (
        "Regenerate support report (HTML)"
        if style == "support"
        else "Regenerate stakeholder report (HTML)"
    )
    bundle_lbl = "Support bundle (.tar.gz)" if style == "support" else "Stakeholder bundle (.tar.gz)"
    return [
        (
            "Inspect (paste-friendly summary)",
            f"replayt inspect RUN_ID --output markdown --style {style}",
        ),
        (regen_md_lbl, f"replayt report RUN_ID --format markdown --style {style}"),
        (
            regen_html_lbl,
            f"replayt report RUN_ID --format html --style {style} --out report.html",
        ),
        (
            "Offline timeline HTML",
            f"replayt replay RUN_ID --format html --style {style} --out run.html",
        ),
        (
            bundle_lbl,
            f"replayt bundle-export RUN_ID --out RUN_ID-{bundle_infix}-bundle.tar.gz --report-style {style}",
        ),
        ("Machine-readable inventory", "replayt runs --output json"),
        ("Inspect (JSON for engineers)", "replayt inspect RUN_ID --output json"),
    ]


def runs_inventory_markdown(
    runs_data: list[tuple[str, dict[str, Any], dict[str, Any], int | None]],
    *,
    log_dir: Path,
    sqlite: Path | None,
    limit: int,
    generated_at_iso: str,
    style: Literal["stakeholder", "support"] = "stakeholder",
) -> str:
    """Markdown document: filtered run table plus the same stakeholder handoff commands as single-run reports."""

    if style == "support":
        lines: list[str] = ["## Support triage — run inventory", ""]
    else:
        lines = ["## Recent replayt runs", ""]
    lines.append(f"- **Generated at:** `{generated_at_iso}`")
    ld = str(log_dir).replace("`", "'")
    lines.append(f"- **Log directory:** `{ld}`")
    if sqlite is not None:
        sq = str(sqlite.resolve()).replace("`", "'")
        lines.append(f"- **SQLite mirror:** `{sq}`")
    lines.append(f"- **Listing limit:** `{limit}`")
    lines.append(f"- **Rows shown:** {len(runs_data)}")
    lines.append("")
    if not runs_data:
        lines.append("No runs matched this query.")
    else:
        lines.extend(
            [
                "| run_id | status | workflow | last_event | attention |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for rid, summary, attention, _age in runs_data:
            wf = f"{summary.get('workflow_name')}@{summary.get('workflow_version')}"
            att_raw = str(attention.get("attention_summary") or "").strip()
            att = att_raw if att_raw else "—"
            lines.append(
                f"| {_runs_inventory_md_cell(rid)} | {_runs_inventory_md_cell(summary.get('status'))} | "
                f"{_runs_inventory_md_cell(wf)} | {_runs_inventory_md_cell(summary.get('last_ts'))} | "
                f"{_runs_inventory_md_cell(att)} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Stakeholder CLI handoff",
            "",
            "Replace `RUN_ID` with a run id from the table above. Repeat `--log-dir`, `--log-subdir`, or `--sqlite` "
            "on each command when you are not using the default log store.",
            "",
        ]
    )
    for label, cmd in _runs_inventory_handoff_rows(style):
        safe_cmd = cmd.replace("`", "'")
        lines.append(f"- **{label}:** `{safe_cmd}`")
    lines.extend(
        [
            "",
            "**Paused runs:** read pending `approval_id` values from `replayt inspect RUN_ID --output json`, then "
            "`replayt resume TARGET RUN_ID --approval <approval_id>` (replace `TARGET` with your workflow entry).",
            "",
            "**Failed runs:** use JSON inspect alongside stakeholder or support reports when engineers need payload "
            "detail.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def format_timeline_seq(seq: Any) -> str:
    """Format event ``seq`` for timeline text; tolerates missing or non-integer JSONL."""

    if seq is None:
        return "----"
    try:
        n = int(seq)
    except (TypeError, ValueError):
        s = str(seq).strip()
        return s if s else "----"
    if n < 0:
        return str(n)
    return f"{n:04d}"


def _replay_omit_event_type(typ: str | None, *, style: str) -> bool:
    if style == "default" or not typ:
        return False
    return typ in {"tool_call", "tool_result", "llm_request", "llm_response"}


def replay_timeline_lines(
    events: list[dict[str, Any]],
    *,
    style: Literal["default", "stakeholder", "support"] = "default",
) -> list[str]:
    lines: list[str] = []
    for e in events:
        raw_typ = e.get("type")
        typ_key = jsonl_type_str(raw_typ)
        display_typ = str(raw_typ) if raw_typ is not None else "unknown"
        if _replay_omit_event_type(typ_key, style=style):
            continue
        payload = e.get("payload") or {}
        seq_s = format_timeline_seq(e.get("seq"))
        line = f"{seq_s}  {display_typ}"
        if typ_key in {
            "state_entered",
            "state_exited",
            "transition",
            "run_failed",
            "approval_requested",
            "structured_output",
            "step_note",
            "tool_call",
            "tool_result",
        }:
            raw = json.dumps(payload, ensure_ascii=False, default=str)
            if len(raw) > 500:
                raw = raw[:497] + "..."
            line += f"  {raw}"
        lines.append(line)
    return lines


def _replay_attention_banner_html(events: list[dict[str, Any]]) -> str:
    att = run_attention_summary(events)
    kind = str(att.get("attention_kind") or "none")
    asum = str(att.get("attention_summary") or "").strip()
    if kind == "none":
        return ""
    if asum:
        return (
            '<p class="rp-att"><span class="rp-att-label">attention=</span> '
            f'<code class="rp-att-code">{html.escape(asum)}</code></p>'
        )
    return (
        '<p class="rp-att"><span class="rp-att-label">attention_kind=</span> '
        f'<code class="rp-att-code">{html.escape(kind)}</code></p>'
    )


def replay_html(
    run_id: str,
    events: list[dict[str, Any]],
    *,
    style: Literal["default", "stakeholder", "support"] = "default",
) -> str:
    summary = event_summary(events)
    if style == "support":
        page_title = f"Support handoff — {run_id}"
    elif style == "stakeholder":
        page_title = f"Run timeline — {run_id}"
    else:
        page_title = f"replayt run {run_id}"
    title = html.escape(page_title)
    rows = []
    pre = '<pre class="row">'
    for line in replay_timeline_lines(events, style=style):
        rows.append(f"{pre}{html.escape(line)}</pre>")
    body_rows = "\n".join(rows)
    attention_html = _replay_attention_banner_html(events) if style != "default" else ""
    omit_note = ""
    if style != "default":
        omit_note = (
            '<p class="rp-muted-note">Stakeholder-facing timeline: <code class="rp-att-code">llm_request</code>, '
            '<code class="rp-att-code">llm_response</code>, <code class="rp-att-code">tool_call</code>, and '
            '<code class="rp-att-code">tool_result</code> rows are omitted. '
            "States, transitions, structured outputs, approvals, and failures stay visible.</p>\n"
        )
    handoff_html = ""
    if style in {"stakeholder", "support"}:
        handoff_html = stakeholder_report_handoff_html(run_id, events, report_style=style)
    foot_default = "Generated by replayt (no model calls; timeline from local event store)."
    if style == "default":
        foot_extra = ""
    else:
        foot_extra = (
            f'<p class="foot">For every JSONL row including tool and LLM lines, run '
            f'<code class="rp-att-code">replayt replay {html.escape(run_id)} --format html --style default</code> '
            f"(repeat <code class=\"rp-att-code\">--log-dir</code> / <code class=\"rp-att-code\">--log-subdir</code> "
            f"or <code class=\"rp-att-code\">--sqlite</code> if you used them here).</p>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{title}</title>
  <style>{REPLAY_HTML_CSS}</style>
</head>
<body>
  <main>
    <h1 class="title">{title}</h1>
    <p class="sub">
      status={html.escape(str(summary.get("status")))}
      workflow={html.escape(str(summary.get("workflow_name")))}@{html.escape(str(summary.get("workflow_version")))}
    </p>
    {attention_html}{omit_note}{handoff_html}
    <section class="card">
      {body_rows}
    </section>
    <p class="foot">{foot_default}</p>{foot_extra}
  </main>
</body>
</html>
"""


def parse_tag_filters(raw: list[str] | None) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for t in raw:
        if "=" not in t:
            raise typer.BadParameter(f"Tag filter must be key=value, got: {t!r}")
        k, v = t.split("=", 1)
        out[k] = v
    return out


def tags_match(run_tags: dict[str, str], filters: dict[str, str]) -> bool:
    return all(run_tags.get(k) == v for k, v in filters.items())


def parse_meta_filters(raw: list[str] | None) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for t in raw:
        if "=" not in t:
            raise typer.BadParameter(f"run-meta filter must be key=value, got: {t!r}")
        k, v = t.split("=", 1)
        out[k] = v
    return out


def run_meta_filters_match(run_meta: dict[str, Any], filters: dict[str, str]) -> bool:
    return all(k in run_meta and str(run_meta[k]) == v for k, v in filters.items())


def experiment_filters_match(run_exp: dict[str, Any], filters: dict[str, str]) -> bool:
    return all(k in run_exp and str(run_exp[k]) == v for k, v in filters.items())


def parse_tool_name_filters(raw: list[str] | None) -> frozenset[str] | None:
    """Normalize repeatable `--tool` CLI values (exact name match; OR semantics across values)."""
    if not raw:
        return None
    normalized: list[str] = []
    for item in raw:
        name = str(item).strip()
        if not name:
            raise typer.BadParameter(
                "Empty --tool is not allowed; omit the flag or pass a tool `name` "
                "(exact match against JSONL `tool_call` payload `name`; repeat for OR)."
            )
        normalized.append(name)
    return frozenset(normalized)


def parse_note_kind_filters(raw: list[str] | None) -> frozenset[str] | None:
    """Normalize repeatable `--note-kind` CLI values (exact kind match; OR semantics across values)."""
    if not raw:
        return None
    normalized: list[str] = []
    for item in raw:
        kind = str(item).strip()
        if not kind:
            raise typer.BadParameter(
                "Empty --note-kind is not allowed; omit the flag or pass a step_note `kind` "
                "(exact match against JSONL `step_note` payload `kind`; repeat for OR)."
            )
        normalized.append(kind)
    return frozenset(normalized)


def run_matches_tool_name_filter(events: list[dict[str, Any]], wanted: frozenset[str] | None) -> bool:
    if wanted is None:
        return True
    for e in events:
        if e.get("type") != "tool_call":
            continue
        payload = e.get("payload") or {}
        n = payload.get("name")
        if isinstance(n, str) and n in wanted:
            return True
    return False


def parse_structured_schema_name_filters(raw: list[str] | None) -> frozenset[str] | None:
    """Normalize repeatable `--structured-schema` values (exact `schema_name`; OR across values)."""
    if not raw:
        return None
    normalized: list[str] = []
    for item in raw:
        name = str(item).strip()
        if not name:
            raise typer.BadParameter(
                "Empty --structured-schema is not allowed; omit the flag or pass a `schema_name` "
                "(exact match on `structured_output` / `structured_output_failed` and, when present, "
                "`llm_request` / `llm_response` payload `schema_name`; repeat for OR)."
            )
        normalized.append(name)
    return frozenset(normalized)


def run_matches_structured_schema_name_filter(
    events: list[dict[str, Any]], wanted: frozenset[str] | None
) -> bool:
    if wanted is None:
        return True
    for e in events:
        if jsonl_type_str(e.get("type")) not in {
            "structured_output",
            "structured_output_failed",
            "llm_request",
            "llm_response",
        }:
            continue
        payload = e.get("payload") or {}
        sn = payload.get("schema_name")
        if isinstance(sn, str) and sn in wanted:
            return True
    return False


def run_matches_note_kind_filter(events: list[dict[str, Any]], wanted: frozenset[str] | None) -> bool:
    if wanted is None:
        return True
    for e in events:
        if e.get("type") != "step_note":
            continue
        payload = e.get("payload") or {}
        kind = payload.get("kind")
        if isinstance(kind, str) and kind in wanted:
            return True
    return False


def parse_finish_reason_filters(raw: list[str] | None) -> frozenset[str] | None:
    """Normalize repeatable `--finish-reason` values (exact match; OR across values)."""
    if not raw:
        return None
    normalized: list[str] = []
    for item in raw:
        reason = str(item).strip()
        if not reason:
            raise typer.BadParameter(
                "Empty --finish-reason is not allowed; omit the flag or pass an `llm_response` "
                "payload `finish_reason` string (exact match; repeat for OR)."
            )
        normalized.append(reason)
    return frozenset(normalized)


def run_matches_finish_reason_filter(events: list[dict[str, Any]], wanted: frozenset[str] | None) -> bool:
    if wanted is None:
        return True
    for e in events:
        if e.get("type") != "llm_response":
            continue
        payload = e.get("payload") or {}
        fr = payload.get("finish_reason")
        if isinstance(fr, str) and fr in wanted:
            return True
    return False


def payload_llm_model(payload: dict[str, Any]) -> str | None:
    """Resolve logged model id from `effective.model` when present, else top-level `model`."""
    eff = payload.get("effective")
    if isinstance(eff, dict):
        m = eff.get("model")
        if isinstance(m, str) and m:
            return m
    m = payload.get("model")
    if isinstance(m, str) and m:
        return m
    return None


def parse_llm_model_filters(raw: list[str] | None) -> frozenset[str] | None:
    """Normalize repeatable `--llm-model` values (exact match; OR across values)."""
    if not raw:
        return None
    normalized: list[str] = []
    for item in raw:
        model = str(item).strip()
        if not model:
            raise typer.BadParameter(
                "Empty --llm-model is not allowed; omit the flag or pass a model id "
                "(exact match on `llm_request` / `llm_response` / structured-output payload "
                "`effective.model`, with legacy fallback to top-level `model`; repeat for OR)."
            )
        normalized.append(model)
    return frozenset(normalized)


def run_matches_llm_model_filter(events: list[dict[str, Any]], wanted: frozenset[str] | None) -> bool:
    if wanted is None:
        return True
    for e in events:
        typ = jsonl_type_str(e.get("type"))
        if typ not in {"llm_request", "llm_response", "structured_output", "structured_output_failed"}:
            continue
        payload = e.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        m = payload_llm_model(payload)
        if m is not None and m in wanted:
            return True
    return False


def parse_iso_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        s = str(ts)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def run_diff_data(
    events: list[dict[str, Any]],
    *,
    llm_model_filter: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Extract comparable data from a run's events.

    When ``llm_model_filter`` is set, structured outputs and LLM latency counts only include
    events whose logged model id matches (``payload_llm_model``); states, status, and tool
    calls still reflect the full run.
    """

    def _model_ok(payload: Any) -> bool:
        if llm_model_filter is None:
            return True
        if not isinstance(payload, dict):
            return False
        m = payload_llm_model(payload)
        return m is not None and m in llm_model_filter

    states: list[str] = []
    outputs: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    status = "unknown"
    total_latency_ms = 0
    llm_count = 0
    for e in events:
        typ = e.get("type")
        payload = e.get("payload") or {}
        if typ == "state_entered":
            states.append(str(payload.get("state", "")))
        elif typ == "structured_output":
            if not _model_ok(payload):
                continue
            outputs.append(
                {
                    "schema_name": str(payload.get("schema_name", "")),
                    "state": payload.get("state"),
                    "seq": e.get("seq"),
                    "data": payload.get("data"),
                }
            )
        elif typ == "tool_call":
            tool_calls.append({"tool": payload.get("name"), "args": payload.get("arguments")})
        elif typ == "llm_response":
            if not _model_ok(payload):
                continue
            ms = payload.get("latency_ms")
            if isinstance(ms, int):
                total_latency_ms += ms
                llm_count += 1
        elif typ == "run_completed":
            status = payload.get("status", status)
        elif typ == "run_paused":
            status = "paused"
    return {
        "states_visited": states,
        "structured_outputs": outputs,
        "tool_calls": tool_calls,
        "status": status,
        "total_latency_ms": total_latency_ms,
        "llm_calls": llm_count,
    }


def parse_duration(value: str) -> int | None:
    """Parse a human duration like '90d', '24h', '30d' into seconds. Returns None on failure."""
    m = re.fullmatch(r"(\d+)\s*([dhms])", value.strip().lower())
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    multipliers = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return n * multipliers[unit]
