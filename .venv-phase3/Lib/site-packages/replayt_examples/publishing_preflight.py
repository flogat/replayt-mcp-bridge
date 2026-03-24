from __future__ import annotations

from pydantic import BaseModel, Field

from replayt.workflow import Workflow

wf = Workflow("content_publishing_preflight")
wf.set_initial("checklist")
wf.note_transition("checklist", "approval")
wf.note_transition("approval", "finalize")
wf.note_transition("approval", "abort")
wf.note_transition("finalize", "done")
wf.note_transition("abort", "done")


class ChecklistResult(BaseModel):
    passes: bool
    issues: list[str] = Field(default_factory=list)
    editor_summary: str


@wf.step("checklist")
def checklist(ctx) -> str:
    draft = ctx.get("draft")
    audience = ctx.get("audience", "general")
    if not isinstance(draft, str):
        raise ValueError("context requires draft: str (see replayt_examples tutorial README)")
    result = ctx.llm.parse(
        ChecklistResult,
        messages=[
            {
                "role": "system",
                "content": (
                    "Evaluate generated content against a strict preflight checklist: "
                    "claims supported, no PII, correct tone, disclaimers if needed, title accuracy."
                ),
            },
            {
                "role": "user",
                "content": f"audience={audience}\n--- draft ---\n{draft}",
            },
        ],
    )
    ctx.set("checklist", result.model_dump())
    ctx.set(
        "approval_summary",
        f"passes={result.passes}; issues={len(result.issues)}; {result.editor_summary}",
    )
    return "approval"


@wf.step("approval")
def approval(ctx) -> str:
    if ctx.is_approved("publish"):
        return "finalize"
    if ctx.is_rejected("publish"):
        return "abort"
    ctx.request_approval(
        "publish",
        summary=str(ctx.get("approval_summary") or "Approve publish?"),
        details={"checklist": ctx.get("checklist") or {}},
    )


@wf.step("finalize")
def finalize(ctx) -> str:
    ctx.set("publish_status", "approved")
    return "done"


@wf.step("abort")
def abort(ctx) -> str:
    ctx.set("publish_status", "aborted")
    return "done"


@wf.step("done")
def done(ctx) -> str | None:
    return None
