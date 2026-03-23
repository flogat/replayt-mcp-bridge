"""Tutorial 7: summarize multiple pieces of customer feedback into themes."""

from __future__ import annotations

from pydantic import BaseModel, Field

from replayt.workflow import Workflow

wf = Workflow("feedback_clustering")
wf.set_initial("cluster")
wf.note_transition("cluster", "done")


class FeedbackTheme(BaseModel):
    theme: str
    priority: str = Field(description="One of high, medium, low")
    representative_quotes: list[str] = Field(default_factory=list)
    recommended_owner: str


class FeedbackSummary(BaseModel):
    themes: list[FeedbackTheme] = Field(default_factory=list)
    release_note_hint: str


@wf.step("cluster")
def cluster(ctx) -> str:
    product = str(ctx.get("product") or "product")
    feedback = ctx.get("feedback") or []
    if not isinstance(feedback, list) or not all(isinstance(item, str) for item in feedback):
        raise ValueError("context requires feedback: list[str]")
    summary = ctx.llm.parse(
        FeedbackSummary,
        messages=[
            {
                "role": "system",
                "content": "You are a product ops analyst. Cluster customer feedback into actionable themes.",
            },
            {
                "role": "user",
                "content": f"Product: {product}\nFeedback items:\n- " + "\n- ".join(feedback),
            },
        ],
    )
    ctx.set("feedback_summary", summary.model_dump())
    return "done"


@wf.step("done")
def done(ctx) -> str | None:
    return None
