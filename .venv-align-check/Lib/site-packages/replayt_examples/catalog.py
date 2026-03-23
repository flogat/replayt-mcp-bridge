from __future__ import annotations

import importlib
import json
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExampleSpec:
    key: str
    title: str
    target: str
    description: str
    inputs_example: dict[str, Any]
    llm_backed: bool = False


PACKAGED_EXAMPLES: dict[str, ExampleSpec] = {
    "hello-world": ExampleSpec(
        key="hello-world",
        title="Hello world",
        target="replayt_examples.e01_hello_world:wf",
        description="Smallest possible replayt workflow; deterministic and offline-friendly.",
        inputs_example={"customer_name": "Sam"},
    ),
    "intake-normalization": ExampleSpec(
        key="intake-normalization",
        title="Intake normalization",
        target="replayt_examples.e02_intake_normalization:wf",
        description="Validate and normalize raw lead intake before later routing.",
        inputs_example={
            "lead": {
                "name": "  Sam Patel ",
                "email": "SAM@example.com ",
                "company": "Northwind",
                "message": "Need a demo for 40 seats",
            }
        },
    ),
    "support-routing": ExampleSpec(
        key="support-routing",
        title="Support routing",
        target="replayt_examples.e03_support_routing:wf",
        description="Explicit support queue and SLA routing with no LLM dependency.",
        inputs_example={
            "ticket": {
                "channel": "email",
                "subject": "Payment failed twice",
                "body": "Enterprise invoice card was declined during renewal.",
                "customer_tier": "enterprise",
            }
        },
    ),
    "issue-triage": ExampleSpec(
        key="issue-triage",
        title="GitHub issue triage",
        target="replayt_examples.issue_triage:wf",
        description="Structured-output bug triage that can route or request missing details.",
        inputs_example={
            "issue": {
                "title": "Crash on save",
                "body": "Open app, click save, stack trace appears, expected file write.",
            }
        },
        llm_backed=True,
    ),
    "refund-policy": ExampleSpec(
        key="refund-policy",
        title="Refund policy",
        target="replayt_examples.refund_policy:wf",
        description="Constrained support decision using one structured model output.",
        inputs_example={
            "ticket": "My order arrived damaged and I need a refund.",
            "order": {
                "order_id": "ORD-1001",
                "amount_cents": 12999,
                "delivered": True,
                "days_since_delivery": 3,
            },
        },
        llm_backed=True,
    ),
    "publishing-preflight": ExampleSpec(
        key="publishing-preflight",
        title="Publishing preflight",
        target="replayt_examples.publishing_preflight:wf",
        description="Structured review plus a human approval gate before shipping content.",
        inputs_example={"draft": "We guarantee 200% returns forever.", "audience": "general"},
        llm_backed=True,
    ),
}


def packaged_example_cli_snippets(key: str) -> dict[str, str]:
    """Copy-paste one-liners for docs and ``replayt try --list --output json``."""

    return {
        "try_offline": f"replayt try --example {key}",
        "try_live": f"replayt try --example {key} --live",
        "try_dry_check": f"replayt try --example {key} --dry-check",
        "copy_to_dot": f"replayt try --example {key} --copy-to .",
    }


_TRY_SNIPPET_BASE_KEYS = frozenset(packaged_example_cli_snippets("hello-world"))

TRY_PRINT_SNIPPET_KEYS: frozenset[str] = _TRY_SNIPPET_BASE_KEYS | frozenset({"target", "run", "run_dry_check"})


def format_try_print_snippet_command(
    spec: ExampleSpec,
    snippet_key: str,
    *,
    resolved_inputs_json: str,
) -> str:
    """Build a single shell-oriented line for ``replayt try --print-snippet`` (stdout)."""

    snippets = packaged_example_cli_snippets(spec.key)
    if snippet_key in snippets:
        return snippets[snippet_key]
    if snippet_key == "target":
        return spec.target
    if snippet_key in ("run", "run_dry_check"):
        compact = json.dumps(
            json.loads(resolved_inputs_json),
            separators=(",", ":"),
            sort_keys=True,
        )
        cmd = f"replayt run {spec.target} --inputs-json {shlex.quote(compact)}"
        if snippet_key == "run_dry_check":
            cmd += " --dry-check"
        return cmd
    raise KeyError(snippet_key)


def list_packaged_examples() -> list[ExampleSpec]:
    return [PACKAGED_EXAMPLES[key] for key in sorted(PACKAGED_EXAMPLES)]


def get_packaged_example(key: str) -> ExampleSpec:
    try:
        return PACKAGED_EXAMPLES[key]
    except KeyError as exc:
        known = ", ".join(sorted(PACKAGED_EXAMPLES))
        raise KeyError(f"Unknown example {key!r}; choose from: {known}") from exc


def copy_packaged_example_to_directory(spec: ExampleSpec, dest_dir: Path, *, force: bool) -> tuple[Path, Path]:
    """Copy the example module and catalog inputs into *dest_dir* (``workflow.py``, ``inputs.example.json``)."""

    dest = dest_dir.resolve()
    if dest.is_file():
        raise ValueError(f"Destination must be a directory, not a file: {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    module_name = spec.target.split(":", 1)[0]
    mod = importlib.import_module(module_name)
    src_file = getattr(mod, "__file__", None)
    if not src_file:
        raise ValueError(f"Module {module_name!r} has no __file__; cannot copy source")
    src_path = Path(src_file).resolve()
    dst_py = dest / "workflow.py"
    dst_inputs = dest / "inputs.example.json"
    if not force:
        conflicts = [p for p in (dst_py, dst_inputs) if p.exists()]
        if conflicts:
            names = ", ".join(str(p) for p in conflicts)
            raise FileExistsError(
                f"Refusing to overwrite (use --force): {names}"
            )
    shutil.copy2(src_path, dst_py)
    dst_inputs.write_text(json.dumps(spec.inputs_example, indent=2) + "\n", encoding="utf-8")
    return dst_py, dst_inputs
