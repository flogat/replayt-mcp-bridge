"""Tutorial 6: structured LLM output for sales call preparation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from replayt.workflow import Workflow

wf = Workflow("sales_call_brief")
wf.set_initial("draft_brief")
wf.note_transition("draft_brief", "done")


class CallBrief(BaseModel):
    customer_stage: str = Field(description="One of discovery, evaluation, procurement, expansion")
    top_goals: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommended_talking_points: list[str] = Field(default_factory=list)
    next_step: str


@wf.step("draft_brief")
def draft_brief(ctx) -> str:
    account_name = str(ctx.get("account_name") or "Unknown account")
    notes = str(ctx.get("notes") or "")
    brief = ctx.llm.parse(
        CallBrief,
        messages=[
            {
                "role": "system",
                "content": "You prepare concise sales call briefs from CRM notes.",
            },
            {
                "role": "user",
                "content": f"Account: {account_name}\nCRM notes:\n{notes}",
            },
        ],
    )
    ctx.set("call_brief", brief.model_dump())
    return "done"


@wf.step("done")
def done(ctx) -> str | None:
    return None
