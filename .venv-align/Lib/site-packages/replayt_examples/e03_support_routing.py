"""Tutorial 3: deterministic branching for support ticket routing."""

from __future__ import annotations

from pydantic import BaseModel, Field

from replayt.workflow import Workflow

wf = Workflow("support_routing")
wf.set_initial("ingest")
wf.note_transition("ingest", "route")
wf.note_transition("route", "done")


class Ticket(BaseModel):
    channel: str
    subject: str = Field(min_length=4)
    body: str = Field(min_length=10)
    customer_tier: str = Field(default="standard")


@wf.step("ingest")
def ingest(ctx) -> str:
    raw = ctx.get("ticket")
    if not isinstance(raw, dict):
        raise ValueError("context requires ticket: object")
    ctx.set("ticket", Ticket.model_validate(raw).model_dump())
    return "route"


@wf.step("route")
def route(ctx) -> str:
    ticket = Ticket.model_validate(ctx.get("ticket"))
    text = f"{ticket.subject}\n{ticket.body}".lower()

    queue = "general"
    priority = "normal"
    if "security" in text or "breach" in text:
        queue = "security"
        priority = "urgent"
    elif "payment" in text or "invoice" in text or "billing" in text:
        queue = "billing"
    elif "bug" in text or "error" in text or "failed" in text:
        queue = "technical"

    if ticket.customer_tier.lower() in {"enterprise", "vip"}:
        priority = "high" if priority == "normal" else priority

    ctx.set(
        "routing_decision",
        {
            "queue": queue,
            "priority": priority,
            "sla_hours": 1 if priority == "urgent" else 4 if priority == "high" else 24,
        },
    )
    return "done"


@wf.step("done")
def done(ctx) -> str | None:
    return None
