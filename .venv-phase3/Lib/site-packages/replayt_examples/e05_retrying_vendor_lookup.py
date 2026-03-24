"""Tutorial 5: retries for a flaky lookup step."""

from __future__ import annotations

from replayt.types import RetryPolicy
from replayt.workflow import Workflow

wf = Workflow("retrying_vendor_lookup")
wf.set_initial("lookup")
wf.note_transition("lookup", "summarize")
wf.note_transition("summarize", "done")


@wf.step("lookup", retries=RetryPolicy(max_attempts=3, backoff_seconds=0.0))
def lookup(ctx) -> str:
    vendor_name = str(ctx.get("vendor_name") or "unknown vendor")
    attempts = int(ctx.get("lookup_attempts") or 0) + 1
    ctx.set("lookup_attempts", attempts)
    if attempts < 2:
        raise RuntimeError(f"Temporary vendor directory timeout for {vendor_name}")
    ctx.set(
        "vendor_record",
        {
            "vendor_name": vendor_name,
            "status": "active",
            "payment_terms": "net-30",
            "risk_level": "low",
        },
    )
    return "summarize"


@wf.step("summarize")
def summarize(ctx) -> str:
    record = dict(ctx.get("vendor_record") or {})
    record["lookup_attempts"] = ctx.get("lookup_attempts")
    ctx.set("lookup_summary", record)
    return "done"


@wf.step("done")
def done(ctx) -> str | None:
    return None
