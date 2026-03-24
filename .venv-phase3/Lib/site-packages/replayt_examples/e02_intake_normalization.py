"""Tutorial 2: validate raw intake data and shape internal context."""

from __future__ import annotations

from pydantic import BaseModel, Field

from replayt.workflow import Workflow

wf = Workflow("intake_normalization")
wf.set_initial("validate")
wf.note_transition("validate", "normalize")
wf.note_transition("normalize", "done")


class RawLead(BaseModel):
    name: str = Field(min_length=2)
    email: str
    company: str = Field(min_length=2)
    message: str = Field(min_length=10)


@wf.step("validate")
def validate(ctx) -> str:
    raw = ctx.get("lead")
    if not isinstance(raw, dict):
        raise ValueError('context requires lead: object (pass --inputs-json "{...}")')
    lead = RawLead.model_validate(raw)
    ctx.set("lead", lead.model_dump())
    return "normalize"


@wf.step("normalize")
def normalize(ctx) -> str:
    lead = RawLead.model_validate(ctx.get("lead"))
    normalized = {
        "name": lead.name.strip().title(),
        "email": lead.email.strip().lower(),
        "company": lead.company.strip(),
        "message": " ".join(lead.message.split()),
        "segment": "enterprise" if "seat" in lead.message.lower() or "demo" in lead.message.lower() else "smb",
    }
    ctx.set("normalized_lead", normalized)
    return "done"


@wf.step("done")
def done(ctx) -> str | None:
    return None
