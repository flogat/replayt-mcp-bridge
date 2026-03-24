from __future__ import annotations

from pydantic import BaseModel, Field

from replayt.workflow import Workflow

wf = Workflow("github_issue_triage")
wf.set_initial("validate")
wf.note_transition("validate", "classify")
wf.note_transition("classify", "respond")
wf.note_transition("classify", "route")
wf.note_transition("classify", "done")
wf.note_transition("respond", "done")
wf.note_transition("route", "done")


class IssuePayload(BaseModel):
    title: str
    body: str


class TriageDecision(BaseModel):
    needs_more_info: bool = Field(description="True if required template fields are missing")
    missing_fields: list[str] = Field(default_factory=list)
    category: str = Field(description="One of bug, feature, question, chore, security")
    priority: str = Field(description="One of P0, P1, P2, P3")
    suggested_label: str


@wf.step("validate")
def validate(ctx) -> str:
    raw = ctx.get("issue")
    if not isinstance(raw, dict):
        raise ValueError("context issue must be a dict (pass --inputs-json)")
    issue = IssuePayload.model_validate(raw)
    ctx.set("issue", issue.model_dump())
    missing: list[str] = []
    if len(issue.title.strip()) < 5:
        missing.append("title")
    if len(issue.body.strip()) < 20:
        missing.append("body")
    ctx.set("validate_missing", missing)
    return "classify"


@wf.step("classify")
def classify(ctx) -> str:
    issue = IssuePayload.model_validate(ctx.get("issue"))
    missing = list(ctx.get("validate_missing") or [])
    if missing:
        ctx.set("missing_fields", missing)
        return "respond"
    decision = ctx.llm.parse(
        TriageDecision,
        messages=[
            {
                "role": "user",
                "content": (
                    "You triage GitHub issues. Given title and body, produce strict fields.\n"
                    f"title: {issue.title}\nbody:\n{issue.body}"
                ),
            },
        ],
    )
    ctx.set("decision", decision.model_dump())
    if decision.needs_more_info:
        return "respond"
    return "route"


@wf.step("respond")
def respond(ctx) -> str:
    missing = ctx.get("missing_fields") or ctx.get("decision", {}).get("missing_fields") or []
    ctx.set(
        "response_template",
        "Thanks! Please add: " + ", ".join(missing) if missing else "Could you clarify repro steps?",
    )
    return "done"


@wf.step("route")
def route(ctx) -> str:
    d = ctx.get("decision") or {}
    ctx.set(
        "routing",
        {
            "queue": d.get("category", "question"),
            "label": d.get("suggested_label", "triage"),
            "priority": d.get("priority", "P2"),
        },
    )
    return "done"


@wf.step("done")
def done(ctx) -> str | None:
    ctx.set("finished", True)
    return None
