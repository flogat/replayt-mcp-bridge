"""Scaffold templates for ``replayt init --template``."""

from __future__ import annotations

from dataclasses import dataclass

INIT_TEMPLATES_SCHEMA = "replayt.init_templates.v1"


@dataclass(frozen=True)
class TemplateSpec:
    content: str
    filename: str
    inputs_example: str
    summary: str
    inputs_filename: str = "inputs.example.json"
    llm_backed: bool = False


TEMPLATE_BASIC = '''\
"""Scaffolded replayt workflow. Run with: replayt run workflow.py --inputs-file inputs.example.json."""

from pathlib import Path

from replayt import LogMode, Runner, Workflow
from replayt.persistence import JSONLStore

wf = Workflow("my_workflow", version="1")
wf.set_initial("hello")


@wf.step("hello")
def hello(ctx):
    customer_name = str(ctx.get("customer_name") or "world")
    ctx.set("message", f"Hello, {customer_name}!")
    return None


if __name__ == "__main__":
    runner = Runner(wf, JSONLStore(Path(".replayt/runs")), log_mode=LogMode.redacted)
    r = runner.run(inputs={})
    print(r.run_id, r.status)
'''

TEMPLATE_APPROVAL = '''\
"""Workflow with an approval gate.

Run with: replayt run workflow.py --inputs-file inputs.example.json.
Approve with: replayt resume workflow.py RUN_ID --approval review
"""

from pathlib import Path

from replayt import LogMode, Runner, Workflow
from replayt.persistence import JSONLStore

wf = Workflow("approval_workflow", version="1")
wf.set_initial("evaluate")
wf.note_transition("evaluate", "finalize")

@wf.step("evaluate")
def evaluate(ctx):
    draft = str(ctx.get("draft") or "Needs human sign-off")
    ctx.set("draft", draft)
    if ctx.is_approved("review"):
        return "finalize"
    ctx.request_approval("review", summary="Please review the draft before finalising.")

@wf.step("finalize")
def finalize(ctx):
    ctx.set("result", "approved and finalised")
    return None


if __name__ == "__main__":
    runner = Runner(wf, JSONLStore(Path(".replayt/runs")), log_mode=LogMode.redacted)
    r = runner.run(inputs={})
    print(r.run_id, r.status)
'''

TEMPLATE_TOOL_USING = '''\
"""Workflow that registers and uses typed tools.

Run with: replayt run workflow.py --inputs-file inputs.example.json.
"""

from pathlib import Path

from replayt import LogMode, Runner, Workflow
from replayt.persistence import JSONLStore

wf = Workflow("tool_workflow", version="1")
wf.set_initial("use_tool")


def add(a: int, b: int) -> int:
    return a + b


@wf.step("use_tool")
def use_tool(ctx):
    ctx.tools.register(add)
    left = int(ctx.get("left", 2))
    right = int(ctx.get("right", 3))
    result = ctx.tools.call("add", {"a": left, "b": right})
    ctx.set("sum", result)
    return None


if __name__ == "__main__":
    runner = Runner(wf, JSONLStore(Path(".replayt/runs")), log_mode=LogMode.redacted)
    r = runner.run(inputs={})
    print(r.run_id, r.status)
'''

TEMPLATE_YAML = '''\
# Declarative YAML workflow. Run with: replayt run workflow.yaml --inputs-file inputs.example.json
# Requires: pip install replayt[yaml]

name: yaml_workflow
version: "1"
initial: greet

steps:
  greet:
    set:
      message: "Hello from YAML workflow"
    next: process

  process:
    set:
      status: "processed"
    next: done

  done:
    set:
      complete: true
'''

TEMPLATE_ISSUE_TRIAGE = '''\
"""Structured issue triage workflow.

Run with: replayt run workflow.py --inputs-file inputs.example.json.
"""

from pathlib import Path

from pydantic import BaseModel, Field

from replayt import LogMode, Runner, Workflow
from replayt.persistence import JSONLStore

wf = Workflow("issue_triage_workflow", version="1")
wf.set_initial("validate")
wf.note_transition("validate", "classify")
wf.note_transition("classify", "respond")
wf.note_transition("classify", "route")
wf.note_transition("respond", "done")
wf.note_transition("route", "done")


class IssuePayload(BaseModel):
    title: str
    body: str


class TriageDecision(BaseModel):
    needs_more_info: bool = Field(description="True when the reporter omitted required context.")
    missing_fields: list[str] = Field(default_factory=list)
    category: str = Field(description="One of bug, feature, question, chore, security")
    priority: str = Field(description="One of P0, P1, P2, P3")
    suggested_label: str


@wf.step("validate")
def validate(ctx):
    raw = ctx.get("issue")
    if not isinstance(raw, dict):
        raise ValueError("context issue must be a dict (pass --inputs-file inputs.example.json)")
    issue = IssuePayload.model_validate(raw)
    ctx.set("issue", issue.model_dump())
    missing = []
    if len(issue.title.strip()) < 5:
        missing.append("title")
    if len(issue.body.strip()) < 20:
        missing.append("body")
    ctx.set("validate_missing", missing)
    return "classify"


@wf.step("classify")
def classify(ctx):
    issue = IssuePayload.model_validate(ctx.get("issue"))
    missing = list(ctx.get("validate_missing") or [])
    if missing:
        ctx.set("missing_fields", missing)
        return "respond"
    decision = ctx.llm.parse(
        TriageDecision,
        messages=[
            {
                "role": "user",
                "content": (
                    "You triage GitHub issues. Given title and body, produce strict fields.\\n"
                    f"title: {issue.title}\\nbody:\\n{issue.body}"
                ),
            }
        ],
    )
    ctx.set("decision", decision.model_dump())
    return "respond" if decision.needs_more_info else "route"


@wf.step("respond")
def respond(ctx):
    missing = ctx.get("missing_fields") or ctx.get("decision", {}).get("missing_fields") or []
    ctx.set(
        "response_template",
        "Thanks! Please add: " + ", ".join(missing) if missing else "Could you clarify repro steps?",
    )
    return "done"


@wf.step("route")
def route(ctx):
    decision = ctx.get("decision") or {}
    ctx.set(
        "routing",
        {
            "queue": decision.get("category", "question"),
            "label": decision.get("suggested_label", "triage"),
            "priority": decision.get("priority", "P2"),
        },
    )
    return "done"


@wf.step("done")
def done(ctx):
    ctx.set("finished", True)
    return None


if __name__ == "__main__":
    runner = Runner(wf, JSONLStore(Path(".replayt/runs")), log_mode=LogMode.redacted)
    result = runner.run(inputs={})
    print(result.run_id, result.status)
'''

TEMPLATE_PUBLISHING_PREFLIGHT = '''\
"""Publishing preflight workflow with a human approval gate.

Run with: replayt run workflow.py --inputs-file inputs.example.json.
Approve with: replayt resume workflow.py RUN_ID --approval publish
"""

from pathlib import Path

from pydantic import BaseModel, Field

from replayt import LogMode, Runner, Workflow
from replayt.persistence import JSONLStore

wf = Workflow("publishing_preflight_workflow", version="1")
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
def checklist(ctx):
    draft = ctx.get("draft")
    audience = str(ctx.get("audience") or "general")
    if not isinstance(draft, str):
        raise ValueError("context requires draft: str (pass --inputs-file inputs.example.json)")
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
            {"role": "user", "content": f"audience={audience}\\n--- draft ---\\n{draft}"},
        ],
    )
    ctx.set("checklist", result.model_dump())
    ctx.set(
        "approval_summary",
        f"passes={result.passes}; issues={len(result.issues)}; {result.editor_summary}",
    )
    return "approval"


@wf.step("approval")
def approval(ctx):
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
def finalize(ctx):
    ctx.set("publish_status", "approved")
    return "done"


@wf.step("abort")
def abort(ctx):
    ctx.set("publish_status", "aborted")
    return "done"


@wf.step("done")
def done(ctx):
    return None


if __name__ == "__main__":
    runner = Runner(wf, JSONLStore(Path(".replayt/runs")), log_mode=LogMode.redacted)
    result = runner.run(inputs={})
    print(result.run_id, result.status)
'''

TEMPLATES: dict[str, TemplateSpec] = {
    "basic": TemplateSpec(
        content=TEMPLATE_BASIC,
        filename="workflow.py",
        inputs_example='{\n  "customer_name": "Sam"\n}\n',
        summary="Single-step hello workflow; deterministic, no LLM.",
    ),
    "approval": TemplateSpec(
        content=TEMPLATE_APPROVAL,
        filename="workflow.py",
        inputs_example='{\n  "draft": "Launch notes are ready for review."\n}\n',
        summary="Human approval gate with pause and resume.",
    ),
    "tool-using": TemplateSpec(
        content=TEMPLATE_TOOL_USING,
        filename="workflow.py",
        inputs_example='{\n  "left": 2,\n  "right": 3\n}\n',
        summary="Registers a typed Python tool and logs tool_call results.",
    ),
    "yaml": TemplateSpec(
        content=TEMPLATE_YAML,
        filename="workflow.yaml",
        inputs_example="{}\n",
        summary="YAML-defined workflow graph (install replayt[yaml]).",
    ),
    "issue-triage": TemplateSpec(
        content=TEMPLATE_ISSUE_TRIAGE,
        filename="workflow.py",
        inputs_example=(
            '{\n'
            '  "issue": {\n'
            '    "title": "Crash on save",\n'
            '    "body": "Open app, click save, stack trace appears, expected file write."\n'
            "  }\n"
            "}\n"
        ),
        summary="Structured LLM triage for GitHub-style issues.",
        llm_backed=True,
    ),
    "publishing-preflight": TemplateSpec(
        content=TEMPLATE_PUBLISHING_PREFLIGHT,
        filename="workflow.py",
        inputs_example='{\n  "draft": "We guarantee 200% returns forever.",\n  "audience": "general"\n}\n',
        summary="LLM content review plus publish approval gate.",
        llm_backed=True,
    ),
}


def list_init_template_specs() -> list[tuple[str, TemplateSpec]]:
    return [(key, TEMPLATES[key]) for key in sorted(TEMPLATES)]


def init_template_cli_snippets(template_key: str) -> dict[str, str]:
    """Copy-paste argv strings for docs and ``replayt init --list --output json``."""

    spec = TEMPLATES[template_key]
    wf = spec.filename
    inputs_fn = spec.inputs_filename
    out: dict[str, str] = {
        "init_here": f"replayt init --template {template_key}",
        "init_with_ci_github": f"replayt init --template {template_key} --ci github",
        "doctor_target": f"replayt doctor --skip-connectivity --target {wf}",
        "validate_explicit": f"replayt validate {wf} --inputs-file {inputs_fn}",
        "dry_check_explicit": f"replayt run {wf} --dry-check --inputs-file {inputs_fn}",
        "run_explicit": f"replayt run {wf} --inputs-file {inputs_fn}",
        "ci_dry_check_explicit": f"replayt ci {wf} --dry-check --strict-graph --inputs-file {inputs_fn}",
        "dry_check": "replayt run --dry-check",
        "run": "replayt run",
    }
    if spec.llm_backed:
        out["dry_run"] = "replayt run --dry-run"
    return out
