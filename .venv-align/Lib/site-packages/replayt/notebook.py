from __future__ import annotations

import html
import json
from typing import TYPE_CHECKING, Any

from replayt.graph_export import m_id as _graph_m_id
from replayt.graph_export import mermaid_label as _mermaid_label

if TYPE_CHECKING:
    from replayt.persistence.base import EventStore
    from replayt.workflow import Workflow

try:
    from IPython.display import HTML as _IPyHTML
    from IPython.display import display as _ipython_display

    _HAS_IPYTHON = True
except ImportError:
    _HAS_IPYTHON = False
    _IPyHTML = None  # type: ignore[assignment,misc]
    _ipython_display = None  # type: ignore[assignment,misc]

# Embedded styles only; no third-party script CDNs (local-first; see README design principles).
_NOTEBOOK_STYLES = """
.replayt-nb { font-family: ui-sans-serif, system-ui, sans-serif; color: #111827; }
.replayt-nb-graph-pre {
  margin: 0; padding: 0.75rem; background: #f9fafb; border: 1px solid #e5e7eb;
  border-radius: 0.375rem; font-size: 0.75rem; white-space: pre-wrap; overflow-x: auto;
}
.replayt-nb-graph-note { margin: 0.5rem 0 0; font-size: 0.75rem; color: #6b7280; }
.replayt-nb-graph-note code { font-family: ui-monospace, monospace; font-size: 0.7rem; }
.replayt-nb-run { max-width: 48rem; margin: 0 auto; padding: 1rem; }
.replayt-nb-run-title { font-size: 1.125rem; font-weight: 700; margin: 0 0 0.75rem; }
.replayt-nb-run-title code { color: #4f46e5; font-size: 1em; }
.replayt-nb-row { padding: 0.5rem 0 0.5rem 1rem; margin-bottom: 0.25rem; border-left: 4px solid #e5e7eb; }
.replayt-nb-row--state { border-left-color: #a5b4fc; }
.replayt-nb-row-head { display: flex; align-items: center; gap: 0.5rem; }
.replayt-nb-row-idx { font-size: 0.75rem; color: #9ca3af; font-family: ui-monospace, monospace;
  width: 1.5rem; text-align: right; flex-shrink: 0; }
.replayt-nb-row-ts { font-size: 0.75rem; color: #9ca3af; }
.replayt-nb-row-body { margin-left: 2rem; font-size: 0.875rem; }
.replayt-nb-badge { display: inline-block; padding: 0.125rem 0.5rem; font-size: 0.75rem;
  font-weight: 600; border-radius: 0.25rem; }
.replayt-nb-badge--run_started { background: #dbeafe; color: #1e40af; }
.replayt-nb-badge--state_entered { background: #e0e7ff; color: #3730a3; }
.replayt-nb-badge--structured_output { background: #f3e8ff; color: #6b21a8; }
.replayt-nb-badge--tool_call { background: #fef3c7; color: #92400e; }
.replayt-nb-badge--tool_result { background: #fffbeb; color: #b45309; }
.replayt-nb-badge--run_completed { background: #dcfce7; color: #166534; }
.replayt-nb-badge--run_failed { background: #fee2e2; color: #991b1b; }
.replayt-nb-badge--run_paused { background: #fef9c3; color: #854d0e; }
.replayt-nb-badge--transition { background: #f3f4f6; color: #4b5563; }
.replayt-nb-badge--default { background: #f3f4f6; color: #1f2937; }
.replayt-nb-json { margin-top: 0.25rem; background: #f9fafb; padding: 0.5rem; border-radius: 0.25rem;
  font-size: 0.75rem; overflow-x: auto; }
.replayt-nb-details { margin-top: 0.25rem; }
.replayt-nb-summary { cursor: pointer; font-size: 0.875rem; color: #9333ea; }
.replayt-nb-err { color: #b91c1c; }
"""


def _m_id(state: str) -> str:
    return _graph_m_id(state)


def _build_mermaid_source(wf: Workflow) -> str:
    lines = ["graph TD"]
    for name in wf.step_names():
        label = _mermaid_label(name)
        nid = _m_id(name)
        if name == wf.initial_state:
            lines.append(f'    {nid}["{_mermaid_label(f"{name} (start)")}"]')
        else:
            lines.append(f'    {nid}["{label}"]')
    for src, dst in wf.edges():
        lines.append(f"    {_m_id(src)} --> {_m_id(dst)}")
    return "\n".join(lines)


def display_graph(wf: Workflow) -> Any:
    """Show workflow Mermaid source in a Jupyter cell (no network; diagram via local export or a viewer)."""
    mermaid_src = _build_mermaid_source(wf)

    if not _HAS_IPYTHON:
        print(mermaid_src)
        return None

    html_str = (
        f"<style>{_NOTEBOOK_STYLES}</style>"
        '<div class="replayt-nb">'
        f'<pre class="replayt-nb-graph-pre">{html.escape(mermaid_src)}</pre>'
        "<p class=\"replayt-nb-graph-note\">"
        "Mermaid source (offline-friendly). Render with <code>replayt graph …</code>, "
        "VS Code, or any local Mermaid viewer.</p>"
        "</div>"
    )
    obj = _IPyHTML(html_str)
    _ipython_display(obj)
    return obj


def _event_type_badge(typ: str) -> str:
    key = typ if isinstance(typ, str) and typ in {
        "run_started",
        "state_entered",
        "structured_output",
        "tool_call",
        "tool_result",
        "run_completed",
        "run_failed",
        "run_paused",
        "transition",
    } else "default"
    cls = f"replayt-nb-badge replayt-nb-badge--{key}"
    return f'<span class="{cls}">{html.escape(typ)}</span>'


def _render_payload_detail(typ: str, payload: dict[str, Any]) -> str:
    if typ == "run_started":
        parts = [f"<strong>workflow:</strong> {html.escape(str(payload.get('workflow_name', '')))}"]
        if payload.get("inputs"):
            parts.append(f"<strong>inputs:</strong> {html.escape(json.dumps(payload['inputs'], default=str))}")
        return " &middot; ".join(parts)

    if typ == "state_entered":
        return f"<strong>state:</strong> {html.escape(str(payload.get('state', '')))}"

    if typ == "structured_output":
        raw = json.dumps(payload, indent=2, default=str)
        escaped = html.escape(raw)
        return (
            "<details class='replayt-nb-details'><summary class='replayt-nb-summary'>show JSON</summary>"
            f"<pre class='replayt-nb-json'>{escaped}</pre></details>"
        )

    if typ in ("tool_call", "tool_result"):
        raw = json.dumps(payload, indent=2, default=str)
        escaped = html.escape(raw)
        return f"<pre class='replayt-nb-json'>{escaped}</pre>"

    if typ == "run_completed":
        status = payload.get("status", "completed")
        return f"<strong>status:</strong> {html.escape(str(status))}"

    if typ == "run_failed":
        err = payload.get("error", {})
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        return f"<strong class='replayt-nb-err'>error:</strong> {html.escape(str(msg))}"

    if payload:
        raw = json.dumps(payload, indent=2, default=str)
        return f"<pre class='replayt-nb-json'>{html.escape(raw)}</pre>"
    return ""


def display_run(store: EventStore, run_id: str) -> Any:
    """Render a run timeline as styled HTML in a Jupyter cell (embedded CSS only; no CDN scripts)."""
    events = store.load_events(run_id)

    rows: list[str] = []
    for i, ev in enumerate(events):
        raw_typ = ev.get("type")
        typ_s = str(raw_typ) if raw_typ is not None else "unknown"
        ts = ev.get("ts", "")
        payload = ev.get("payload") or {}
        badge = _event_type_badge(typ_s)
        detail = _render_payload_detail(typ_s, payload)

        is_state_row = isinstance(raw_typ, str) and raw_typ == "state_entered"
        row_cls = "replayt-nb-row replayt-nb-row--state" if is_state_row else "replayt-nb-row"

        rows.append(
            f'<div class="{row_cls}">'
            f'  <div class="replayt-nb-row-head">'
            f'    <span class="replayt-nb-row-idx">{i}</span>'
            f"    {badge}"
            f'    <span class="replayt-nb-row-ts">{html.escape(str(ts))}</span>'
            f"  </div>"
            f'  <div class="replayt-nb-row-body">{detail}</div>'
            f"</div>"
        )

    html_str = (
        f"<style>{_NOTEBOOK_STYLES}</style>"
        '<div class="replayt-nb">'
        '<div class="replayt-nb-run">'
        f'<h3 class="replayt-nb-run-title">Run <code>{html.escape(run_id)}</code></h3>'
        + "\n".join(rows)
        + "</div></div>"
    )

    if not _HAS_IPYTHON:
        print(html_str)
        return None

    obj = _IPyHTML(html_str)
    _ipython_display(obj)
    return obj
