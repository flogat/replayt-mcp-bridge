from __future__ import annotations

from pydantic import BaseModel, Field

from replayt.workflow import Workflow

wf = Workflow("support_refund_policy")
wf.set_initial("ingest")
wf.note_transition("ingest", "decide")
wf.note_transition("decide", "summarize")
wf.note_transition("summarize", "end")


class OrderMeta(BaseModel):
    order_id: str
    amount_cents: int = Field(ge=0)
    delivered: bool
    days_since_delivery: int = Field(ge=0)


class RefundDecision(BaseModel):
    action: str = Field(description="One of refund, reship, store_credit, deny, escalate")
    reason_codes: list[str] = Field(default_factory=list)
    customer_message: str


@wf.step("ingest")
def ingest(ctx) -> str:
    ticket = ctx.get("ticket")
    meta = ctx.get("order")
    if not isinstance(ticket, str) or not isinstance(meta, dict):
        raise ValueError("context requires ticket: str and order: object (see replayt_examples tutorial README)")
    ctx.set("ticket", ticket)
    ctx.set("order", OrderMeta.model_validate(meta).model_dump())
    return "decide"


@wf.step("decide")
def decide(ctx) -> str:
    order = OrderMeta.model_validate(ctx.get("order"))
    ticket = str(ctx.get("ticket"))
    decision = ctx.llm.parse(
        RefundDecision,
        messages=[
            {
                "role": "system",
                "content": (
                    "You enforce a simple policy: refunds if not delivered or <14 days after delivery "
                    "for defective; partial store credit for late shipping; deny abuse patterns; "
                    "escalate legal threats."
                ),
            },
            {
                "role": "user",
                "content": f"ticket:\n{ticket}\norder:\n{order.model_dump_json()}",
            },
        ],
    )
    ctx.set("decision", decision.model_dump())
    return "summarize"


@wf.step("summarize")
def summarize(ctx) -> str:
    d = ctx.get("decision") or {}
    ctx.set(
        "summary_for_agent",
        {
            "action": d.get("action"),
            "reason_codes": d.get("reason_codes"),
            "customer_message": d.get("customer_message"),
        },
    )
    return "end"


@wf.step("end")
def end(ctx) -> str | None:
    ctx.set("completed", True)
    return None
