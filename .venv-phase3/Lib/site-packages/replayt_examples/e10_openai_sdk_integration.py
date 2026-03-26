"""Tutorial 10: using the official OpenAI Python SDK inside replayt steps.

Demonstrates function calling with Pydantic validation, streaming with a
structured summary pass, and proper ctx.set() so everything is auditable.

Requirements: pip install openai
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from replayt.workflow import Workflow

wf = Workflow("openai_sdk_integration", version="1")
wf.set_initial("classify")
wf.note_transition("classify", "enrich")
wf.note_transition("enrich", "summarize")
wf.note_transition("summarize", "done")


class Classification(BaseModel):
    category: str = Field(description="One of: bug, feature, question, docs")
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class Enrichment(BaseModel):
    priority: str = Field(description="One of: p0, p1, p2, p3")
    affected_component: str
    suggested_assignee: str


class StreamSummary(BaseModel):
    headline: str
    key_points: list[str]


@wf.step("classify")
def classify(ctx) -> str:
    """Use the OpenAI SDK with function calling / response_format to classify an issue."""
    from openai import OpenAI

    client = OpenAI()
    issue_title = str(ctx.get("issue_title") or "Untitled")
    issue_body = str(ctx.get("issue_body") or "")

    response = client.chat.completions.create(
        model="anthropic/claude-sonnet-4.6",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Classify the GitHub issue. Return JSON with fields: "
                    "category (bug|feature|question|docs), confidence (0-1), reasoning."
                ),
            },
            {"role": "user", "content": f"Title: {issue_title}\nBody: {issue_body}"},
        ],
    )
    text = response.choices[0].message.content or "{}"
    result = Classification.model_validate_json(text)
    ctx.set("classification", result.model_dump())

    usage = response.usage
    if usage:
        ctx.set("classify_tokens", {
            "prompt": usage.prompt_tokens,
            "completion": usage.completion_tokens,
        })
    return "enrich"


@wf.step("enrich")
def enrich(ctx) -> str:
    """Use the OpenAI SDK with tools parameter for function calling."""
    from openai import OpenAI

    client = OpenAI()
    classification = ctx.get("classification") or {}

    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "set_enrichment",
                "description": "Set the enrichment metadata for the issue.",
                "parameters": Enrichment.model_json_schema(),
            },
        }
    ]

    response = client.chat.completions.create(
        model="anthropic/claude-sonnet-4.6",
        temperature=0,
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "set_enrichment"}},
        messages=[
            {
                "role": "system",
                "content": "Given the classification, determine priority, affected component, and suggested assignee.",
            },
            {
                "role": "user",
                "content": json.dumps(classification),
            },
        ],
    )

    tool_call = response.choices[0].message.tool_calls
    if tool_call:
        args = json.loads(tool_call[0].function.arguments)
        enrichment = Enrichment.model_validate(args)
        ctx.set("enrichment", enrichment.model_dump())
    return "summarize"


@wf.step("summarize")
def summarize(ctx) -> str:
    """Stream a long response, accumulate text, then derive a structured summary via ctx.llm.parse."""
    from openai import OpenAI

    client = OpenAI()
    classification = ctx.get("classification") or {}
    enrichment = ctx.get("enrichment") or {}

    stream = client.chat.completions.create(
        model="anthropic/claude-sonnet-4.6",
        stream=True,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Write a detailed triage note for this issue.\n"
                    f"Classification: {json.dumps(classification)}\n"
                    f"Enrichment: {json.dumps(enrichment)}"
                ),
            },
        ],
    )
    parts: list[str] = []
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            parts.append(delta)
    full_text = "".join(parts)
    ctx.set("triage_note_raw", full_text[:50_000])

    summary = ctx.llm.parse(
        StreamSummary,
        messages=[
            {
                "role": "user",
                "content": f"Summarize this triage note as JSON (headline + key_points):\n{full_text[:8000]}",
            }
        ],
    )
    ctx.set("triage_summary", summary.model_dump())
    return "done"


@wf.step("done")
def done(ctx) -> str | None:
    return None
