"""Tutorial 9: incident coordination with tools and executive approval."""

from __future__ import annotations

from pydantic import BaseModel, Field

from replayt.workflow import Workflow

wf = Workflow("incident_response")
wf.set_initial("assess")
wf.note_transition("assess", "stabilize")
wf.note_transition("stabilize", "exec_review")
wf.note_transition("exec_review", "announce")
wf.note_transition("exec_review", "internal_only")
wf.note_transition("announce", "done")
wf.note_transition("internal_only", "done")


class Incident(BaseModel):
    service: str
    error_rate: float = Field(ge=0)
    customer_impact: str = Field(min_length=5)
    suspected_cause: str = Field(min_length=5)


@wf.step("assess")
def assess(ctx) -> str:
    @ctx.tools.register
    def page_on_call(service: str, severity: str) -> dict[str, str]:
        return {"service": service, "severity": severity, "page_status": "sent"}

    @ctx.tools.register
    def create_statuspage_draft(service: str, impact: str) -> dict[str, str]:
        return {
            "headline": f"Investigating elevated errors in {service}",
            "body": f"We are investigating customer impact: {impact}.",
        }

    raw = ctx.get("incident")
    if not isinstance(raw, dict):
        raise ValueError("context requires incident: object")
    incident = Incident.model_validate(raw)
    severity = "sev1" if incident.error_rate >= 10 else "sev2" if incident.error_rate >= 3 else "sev3"
    ctx.set("incident", incident.model_dump())
    ctx.set("severity", severity)
    return "stabilize"


@wf.step("stabilize")
def stabilize(ctx) -> str:
    incident = Incident.model_validate(ctx.get("incident"))
    severity = str(ctx.get("severity"))
    page_result = ctx.tools.call("page_on_call", {"service": incident.service, "severity": severity})
    draft = ctx.tools.call(
        "create_statuspage_draft",
        {"service": incident.service, "impact": incident.customer_impact},
    )
    ctx.set("stabilization", {"page": page_result, "statuspage_draft": draft})
    return "exec_review"


@wf.step("exec_review")
def exec_review(ctx) -> str:
    severity = str(ctx.get("severity"))
    if severity != "sev1":
        return "internal_only"
    if ctx.is_approved("exec_comms"):
        return "announce"
    if ctx.is_rejected("exec_comms"):
        return "internal_only"
    ctx.request_approval(
        "exec_comms",
        summary="Publish external status page update for sev1 incident?",
        details={
            "incident": ctx.get("incident") or {},
            "stabilization": ctx.get("stabilization") or {},
        },
    )


@wf.step("announce")
def announce(ctx) -> str:
    ctx.set("communication_plan", "external_statuspage_and_internal_slack")
    return "done"


@wf.step("internal_only")
def internal_only(ctx) -> str:
    ctx.set("communication_plan", "internal_updates_only")
    return "done"


@wf.step("done")
def done(ctx) -> str | None:
    return None
