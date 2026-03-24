from __future__ import annotations

import hashlib
import html

from replayt.workflow import Workflow


def mermaid_label(text: str) -> str:
    """Escape Mermaid node labels so quotes and HTML-sensitive characters stay parse-safe."""

    return html.escape(str(text), quote=True)


def workflow_to_mermaid(wf: Workflow) -> str:
    lines: list[str] = ["flowchart TD"]
    init = wf.initial_state or "start"
    lines.append(f'  _entry(["{mermaid_label(f"entry: {init}")}"])')
    for n in wf.step_names():
        lines.append(f'  {m_id(n)}["{mermaid_label(n)}"]')
    if wf.initial_state:
        lines.append(f"  _entry --> {m_id(wf.initial_state)}")
    for a, b in wf.edges():
        lines.append(f"  {m_id(a)} --> {m_id(b)}")
    if not wf.edges() and wf.initial_state:
        for n in wf.step_names():
            if n == wf.initial_state:
                continue
            lines.append(f"  {m_id(wf.initial_state)} -. possible .-> {m_id(n)}")
    return "\n".join(lines) + "\n"


def m_id(state: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in state).strip("_") or "state"
    digest = hashlib.sha1(state.encode("utf-8")).hexdigest()[:8]
    return f"s_{safe}_{digest}"
