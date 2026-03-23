"""Tutorial 8: policy evaluation with a human approval gate."""

from __future__ import annotations

from pydantic import BaseModel, Field

from replayt.workflow import Workflow

wf = Workflow("travel_approval")
wf.set_initial("policy_check")
wf.note_transition("policy_check", "manager_review")
wf.note_transition("manager_review", "book_trip")
wf.note_transition("manager_review", "reject_trip")
wf.note_transition("book_trip", "done")
wf.note_transition("reject_trip", "done")


class TripRequest(BaseModel):
    employee: str
    destination: str
    reason: str = Field(min_length=5)
    estimated_cost: float = Field(gt=0)
    days_notice: int = Field(ge=0)


@wf.step("policy_check")
def policy_check(ctx) -> str:
    raw = ctx.get("trip")
    if not isinstance(raw, dict):
        raise ValueError("context requires trip: object")
    trip = TripRequest.model_validate(raw)
    ctx.set("trip", trip.model_dump())
    policy_flags: list[str] = []
    if trip.estimated_cost > 2500:
        policy_flags.append("high_cost")
    if trip.days_notice < 14:
        policy_flags.append("late_notice")
    ctx.set(
        "travel_policy",
        {
            "auto_approvable": not policy_flags,
            "policy_flags": policy_flags,
        },
    )
    return "manager_review"


@wf.step("manager_review")
def manager_review(ctx) -> str:
    policy = dict(ctx.get("travel_policy") or {})
    if policy.get("auto_approvable"):
        return "book_trip"
    if ctx.is_approved("manager_review"):
        return "book_trip"
    if ctx.is_rejected("manager_review"):
        return "reject_trip"
    trip = ctx.get("trip") or {}
    ctx.request_approval(
        "manager_review",
        summary=(
            f"Approve travel for {trip.get('employee')} to {trip.get('destination')}? "
            f"Flags: {', '.join(policy.get('policy_flags') or ['none'])}"
        ),
        details={"trip": trip, "policy": policy},
    )


@wf.step("book_trip")
def book_trip(ctx) -> str:
    ctx.set("travel_status", "approved_for_booking")
    return "done"


@wf.step("reject_trip")
def reject_trip(ctx) -> str:
    ctx.set("travel_status", "rejected")
    return "done"


@wf.step("done")
def done(ctx) -> str | None:
    return None
