"""Tutorial 11: using the native Anthropic SDK inside replayt steps.

This is a workaround pattern for developers who want anthropic.Anthropic()
as their client rather than an OpenAI-compatible proxy.

LLM traffic from native SDKs is not auto-logged by replayt; ctx.set()
outputs are your audit surface.

Requirements: pip install anthropic
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from replayt.workflow import Workflow

wf = Workflow("anthropic_native", version="1")
wf.set_initial("analyze")
wf.note_transition("analyze", "done")


class Analysis(BaseModel):
    sentiment: str = Field(description="One of: positive, negative, neutral, mixed")
    confidence: float = Field(ge=0.0, le=1.0)
    key_themes: list[str]
    summary: str


@wf.step("analyze")
def analyze(ctx) -> str:
    """Call anthropic.Anthropic() directly; validate with Pydantic; store via ctx.set()."""
    import anthropic

    client = anthropic.Anthropic()
    text = str(ctx.get("text") or "")

    msg = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Analyze the following text and return JSON only with fields: "
                    f"sentiment (positive|negative|neutral|mixed), confidence (0-1), "
                    f"key_themes (list of strings), summary (string).\n\n{text}"
                ),
            }
        ],
    )
    response_text = "".join(
        block.text for block in msg.content if getattr(block, "text", None)
    )
    result = Analysis.model_validate_json(response_text)
    ctx.set("analysis", result.model_dump())

    ctx.set("anthropic_usage", {
        "input_tokens": msg.usage.input_tokens,
        "output_tokens": msg.usage.output_tokens,
    })
    return "done"


@wf.step("done")
def done(ctx) -> str | None:
    return None
