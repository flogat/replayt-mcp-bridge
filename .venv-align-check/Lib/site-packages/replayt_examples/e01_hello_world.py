"""Tutorial 1: smallest possible replayt workflow."""

from __future__ import annotations

from replayt.workflow import Workflow

wf = Workflow("hello_world_tutorial")
wf.set_initial("greet")
wf.note_transition("greet", "done")


@wf.step("greet")
def greet(ctx) -> str:
    customer_name = str(ctx.get("customer_name") or "friend")
    ctx.set("message", f"Hello, {customer_name}! Your first replayt workflow ran.")
    ctx.set("next_action", "Inspect this run, then replay it from the CLI.")
    return "done"


@wf.step("done")
def done(ctx) -> str | None:
    ctx.set("completed", True)
    return None
