"""Tutorial 4: use typed tools for a procurement approval workflow."""

from __future__ import annotations

from pydantic import BaseModel, Field

from replayt.workflow import Workflow

wf = Workflow("tool_using_procurement")
wf.set_initial("intake")
wf.note_transition("intake", "evaluate")
wf.note_transition("evaluate", "done")


class PurchaseRequest(BaseModel):
    employee: str
    department: str
    item: str
    unit_price: float = Field(gt=0)
    quantity: int = Field(gt=0)


class BudgetPolicyInput(BaseModel):
    department: str
    total_cost: float


@wf.step("intake")
def intake(ctx) -> str:
    @ctx.tools.register
    def calculate_total(unit_price: float, quantity: int) -> float:
        return round(unit_price * quantity, 2)

    @ctx.tools.register
    def budget_policy(query: BudgetPolicyInput) -> dict[str, object]:
        limits = {"design": 500.0, "engineering": 1500.0, "ops": 800.0}
        limit = limits.get(query.department.strip().lower(), 300.0)
        return {
            "department_limit": limit,
            "within_policy": query.total_cost <= limit,
        }

    raw = ctx.get("request")
    if not isinstance(raw, dict):
        raise ValueError("context requires request: object")
    ctx.set("request", PurchaseRequest.model_validate(raw).model_dump())
    return "evaluate"


@wf.step("evaluate")
def evaluate(ctx) -> str:
    request = PurchaseRequest.model_validate(ctx.get("request"))
    total_cost = ctx.tools.call(
        "calculate_total",
        {"unit_price": request.unit_price, "quantity": request.quantity},
    )
    policy = ctx.tools.call(
        "budget_policy",
        {"query": {"department": request.department, "total_cost": total_cost}},
    )
    ctx.set(
        "decision",
        {
            "employee": request.employee,
            "item": request.item,
            "total_cost": total_cost,
            "within_policy": policy["within_policy"],
            "recommended_action": "auto_approve" if policy["within_policy"] else "manager_review",
        },
    )
    return "done"


@wf.step("done")
def done(ctx) -> str | None:
    return None
