# Mission: MCP tool bridge for replayt workflow steps

This repository is a **consumer** of [replayt](https://pypi.org/project/replayt/): it adapts replayt-oriented workflow
steps for hosts that speak the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/). It is not a fork of
replayt. Version pins, compatibility shims, and CI live **here**.

**Primary pattern:** **Bridge** (framework bridge)—among core-gap, showcase, bridge, and combinator options in the ecosystem doc, this repo adapts replayt workflow steps for MCP hosts while replayt remains upstream for workflow semantics; see [Framework bridge](REPLAYT_ECOSYSTEM_IDEA.md#3-framework-bridge) and [Your choice](REPLAYT_ECOSYSTEM_IDEA.md#your-choice) in [REPLAYT_ECOSYSTEM_IDEA.md](REPLAYT_ECOSYSTEM_IDEA.md).

## Users and problem

**Maintainers and integrators** need a **single, explicit scope** for how replayt workflow concepts surface as MCP tools,
so pull requests and tool design stay inside replayt’s boundaries instead of drifting into “shadow core.” **Agent and
IDE users** benefit when MCP hosts can invoke the same replayt-backed steps with predictable contracts and documented
compatibility.

## What replayt provides (and what stays here)

**Consumed from replayt (conceptually, as the integration matures):** workflow-step semantics, packaging/import
surface, and any primitives this bridge maps into MCP tool names, parameters, and results—always **as released upstream**,
not vendored forks.

**Consumer-side (this repo only):** MCP server wiring, tool schemas, error mapping, pins against replayt releases,
automated tests at the boundary, changelog notes when upstream behavior affects tools.

## Scope vs upstream

| This package owns | Delegates upstream |
| ----------------- | ------------------ |
| MCP tool surface, adapter code, local docs for integrators | Replayt core behavior, release cadence, canonical workflow definitions |
| CI, test matrix, compatibility policy for **this** bridge | Bug fixes and features inside replayt itself |
| Narrow public API for the bridge package | Broader replayt ecosystem decisions |

**Non-goals:** steering replayt core from this repo; reimplementing replayt; shipping undocumented “magic” tools that
imply guarantees replayt does not provide.

## Success metrics

- **Documentation:** Mission and scope are discoverable from the README; integrators can read scope and non-goals without
  opening code.
- **Automation:** Claimed behavior is covered by **automated tests** (unit and/or contract-style tests at the replayt
  boundary); CI runs them with clear logs and exit codes.
- **Stability:** Supported replayt (and Python) versions are stated or pinned; breaking upstream changes are caught by
  CI and noted for consumers.

## Security and trust boundaries

**Deployment / transport:** How you run the MCP server (stdio, HTTP/SSE, etc.) determines who can reach it; bind
listeners, authentication, and network exposure to a threat model that matches where the bridge runs.

**MCP clients:** Any host the operator connects can invoke registered tools; keep the tool surface small, document side
effects (filesystem, network, subprocesses), and align exposure with organizational access policy.

**Secrets:** Do not embed API keys, tokens, or private paths in code or committed defaults; document required environment
variables and logging/redaction expectations for integrators in **[SECURITY.md](SECURITY.md)** (see also **LLM / demos** below).

**Inputs:** Validate and normalize tool arguments at this bridge’s boundary; avoid passing untrusted strings into shells,
dynamic code execution, or paths outside documented intent.

**Bridge tools (security review):** The current server uses **stdio only** (no bridge-owned network listener). Tool handlers do **not** spawn shells or pass arguments through a system shell; strings go to replayt APIs and `pathlib` as documented in [MCP_TOOLS.md](MCP_TOOLS.md). A **`target`** string has the **same implications as the replayt CLI** (`load_target`): it can cause **Python module import** and **workflow file reads** for paths the server process can access—treat it as **trusted operator input**, not anonymous MCP input. **`store_hint`** (legacy path or optional typed `jsonl:` / `sqlite:` prefix per [MCP_TOOLS.md](MCP_TOOLS.md#store_hint-grammar)) is resolved with `expanduser` and used for **read-only** JSONL directories or SQLite files; it can read any path the process may open, so scope who may attach MCP clients. **`run_id`** is validated via replayt’s store helper before reads. **`persistence_list_run_events`** returns stored event JSON **pass-through by default**; operators may set **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`** (truthy per [SECURITY.md](SECURITY.md)) so the bridge applies key-based redaction to **`events`** before the MCP response. Payloads may still contain sensitive data under non-matching keys—integrators should filter, restrict tool access, or combine both controls as needed. Expected failures map to structured `{ status: error, tool, replayt_surface, message, correlation_id }` objects without Python tracebacks in the return value for the covered paths; the same **`correlation_id`** appears in matching stderr logs—see [MCP_TOOLS.md § Error response shape](MCP_TOOLS.md#error-response-shape). **Unhandled exceptions** from replayt or the workflow under inspection may still surface according to the MCP host/SDK behavior. For a line-by-line handler pass and residual risks, see [Security review (phase 6)](ARCHITECTURE.md#security-review-phase-6) in [ARCHITECTURE.md](ARCHITECTURE.md).

## LLM / demos

This mission is not “LLM showcase first.” If future demos or model calls are added, document models, secrets handling,
cost, and redaction in this doc or in a dedicated doc linked from the README.

## MCP server (stdio)

**Specification.** The following defines the first MCP entrypoint for this bridge.

**User story:** As an **operator**, I want a **runnable MCP server process** (minimal wiring) so that **MCP clients** can attach and use tools without one-off custom integration for each host.

**Intent:** Introduce a **minimal** MCP server using the **official Python MCP SDK** (or an equivalent documented pattern from [modelcontextprotocol.io](https://modelcontextprotocol.io/)), with **stdio** as the default transport. Tool implementations may be stubs initially; the first milestone is a **correct process boundary** and **documented launch** surface.

**Packaging (implemented):**

- Console entry point **`replayt-mcp-bridge`** is declared under `[project.scripts]` in `pyproject.toml`; **`python -m replayt_mcp_bridge`** is also supported via `replayt_mcp_bridge.__main__`.
- README **Quick start** names the **same** canonical commands MCP hosts should run.

**Acceptance criteria (refined, for implementation and review):**

1. **Stdio transport** — The documented primary command runs a server that speaks MCP over **stdin/stdout** (JSON-RPC per MCP), not an HTTP/SSE listener, unless explicitly documented as an additional mode.
2. **Clean startup** — After `pip install -e .` in a fresh project virtualenv, running the documented command produces **no Python traceback** during normal server startup (the process may then block waiting for MCP traffic on stdio, or exit per SDK behavior when stdin closes—both are acceptable if documented).
3. **Discoverable entry surface** — Integrators can find **one** primary launch path in README (console script name and/or `python -m …`) that matches `pyproject.toml` or the package’s documented `__main__` module.
4. **MCP host orientation** — README **Quick start** includes **at least one sentence** aimed at MCP client operators (stdio + how to run the bridge), with a pointer to this section for details.

## Stdio MCP session integration smoke test

**Backlog title:** **CI smoke: subprocess MCP stdio handshake** (same scope as the older phrasing *“Add an integration smoke test over the real stdio MCP session”* in architecture review notes).

**Intent:** Handler-focused tests (for example `tests/test_mcp_tools.py`) exercise replayt boundaries by calling tool functions **in-process**; they do **not** validate FastMCP **stdio framing**, JSON-RPC message flow, or **tool registration** the way a real MCP host does. A **small integration smoke test** closes that gap by driving **at least one full MCP conversation**—session setup (handshake) plus a **single trivial tool call**—against the same **stdio** entrypath operators use.

**User story:** As a **maintainer**, I want **CI** to run that conversation so regressions in bridge wiring, SDK upgrades, or transport show up **before merge**, without replacing the existing fast handler suite.

**Original backlog acceptance criteria (traceability):**

- **Startup / traceback** — Automation must fail if the stdio server exits with a traceback on startup or cannot complete the MCP lifecycle. [`tests/test_mcp_server_stdio.py`](../tests/test_mcp_server_stdio.py) asserts **no traceback** when spawning the bridge **without** sending MCP frames; [`tests/test_mcp_stdio_session_smoke.py`](../tests/test_mcp_stdio_session_smoke.py) catches **wiring / registration / transport** failures when real JSON-RPC traffic runs (subprocess exit, protocol errors, hung session covered by the async wall timeout).
- **Local reproduction** — [CONTRIBUTING.md](../CONTRIBUTING.md) documents running the same checks as CI, including **`pytest tests/test_mcp_stdio_session_smoke.py -q`** for the full handshake + one tool call against **`python -m replayt_mcp_bridge`**.
- **No extra CI network** — The smoke test uses only the **already-installed** bridge, replayt, and MCP Python SDK from **`pip install -e ".[dev]"`**; it does **not** open outbound network connections or fetch remote resources as part of the assertion path.

**Relationship to existing automation:**

- `tests/test_mcp_server_stdio.py` — Confirms the server **process starts** without a traceback; it does **not** send MCP messages.
- `tests/test_mcp_tools.py` — Contract-style coverage at the **handler / replayt** boundary; **no** stdio client.

**Recommended implementation shape (refined):**

- Run inside the **default** CI pytest job (same install as other tests), with an explicit **per-test timeout** in the tens-of-seconds range so a broken server cannot hang the job.
- Prefer the **official MCP Python SDK** **client** running **in the pytest process**: `ClientSession` with `stdio_client`, launching the bridge via `StdioServerParameters` using **`sys.executable`** and **`["-m", "replayt_mcp_bridge"]`** (or the installed console script) and **`cwd`** at the repository root—aligned with [MCP_HOST_CONFIG.md](MCP_HOST_CONFIG.md) and [ARCHITECTURE.md](ARCHITECTURE.md#process-and-transport). **Await handshake / session setup and the tool round-trip** instead of using fixed **`sleep()`** delays for readiness.
- **Happy-path tool:** Prefer **`replayt_version_info`** (proves replayt import and structured success through the full stack). **`replayt_echo`** is an acceptable alternative when the goal is **MCP wiring only**; document the choice in the test module.

**Acceptance criteria (refined, for implementation and review):**

1. **Default CI** — The new test module is collected and run by the standard **`pytest`** step in `.github/workflows/ci.yml` (no extra job required unless maintainers later choose to split slow tests).
2. **Bounded runtime** — The test finishes within **CI-reasonable** wall time and uses **timeouts** (async, subprocess, or pytest) so failures fail **fast**.
3. **Successful tool path** — After MCP session initialization succeeds, **one** `tools/call` (or SDK equivalent) returns a **structured** result consistent with [MCP_TOOLS.md](MCP_TOOLS.md) for the chosen tool (for example `status: "ok"` for `replayt_version_info`).
4. **Clear failures** — Broken stdio, **registration** mistakes (tool missing from `tools/list`), or server startup errors produce **actionable** assertion failures or exceptions (no silent stall).
5. **Determinism** — Avoid **race-prone** “sleep then hope” patterns; rely on protocol-level completion or SDK-managed subprocess lifecycle.

Architecture layering, gaps vs handler tests, and follow-up file naming are recorded under [ARCHITECTURE.md § Architecture review: stdio MCP integration smoke test](ARCHITECTURE.md#architecture-review-stdio-mcp-integration-smoke-test).

## First replayt-backed tool calling (E2E milestone)

**Intent:** Validate that this bridge can call **replayt in-process** with **MCP-appropriate structured payloads**, clear error mapping, and **automated tests** at the handler boundary—before treating a larger tool set as “done.”

**Smallest replayt API (milestone scope):** `replayt_version_info` is the **minimal** integration: it depends on the installed replayt package and the bridge’s `installed_replayt_version` / `installed_replayt_version_tuple` helpers, so it proves **import path, dependency range, and config-free startup** without resolving workflow targets. The **first target-resolution path** is `workflow_contract_snapshot`, which uses `replayt.cli.targets.load_target` and `Workflow.contract()`—the same resolution story as `replayt contract` / `replayt run`.

**Handler expectations:**

- **Happy path** — Return JSON-serializable dicts with `status: "ok"` (or `status: "invalid"` when returning a `replayt.validate_report.v1` object from dry-run validation). FastMCP exposes these as structured tool results to MCP clients.
- **Expected failures** — Map to `{ "status": "error", "tool", "replayt_surface", "message", "correlation_id" }` as documented in [MCP_TOOLS.md](MCP_TOOLS.md), with the same **`correlation_id`** on structured stderr logs per [MCP_TOOLS.md § Error response shape](MCP_TOOLS.md#error-response-shape). Do **not** return raw Python tracebacks inside these objects for the covered failure modes (e.g. `typer.BadParameter` from `load_target`, invalid `run_id`, bad store hints).
- **Observability** — Log at boundaries (server lifecycle, optional debug) without copying **secrets** or unnecessary verbatim client arguments into logs; this surface has no credential parameters—future tools must keep the same discipline.

**Acceptance criteria (refined, for implementation and review):**

1. **Structured success on a replayt-backed tool** — At least `replayt_version_info` returns a stable, documented success shape on a normal install; workflow tools (`workflow_contract_snapshot`, etc.) return documented shapes when given a valid target (see tests for the example target).
2. **Clear tool errors** — Invalid workflow targets, persistence inputs, and similar **expected** failures yield the structured error object (not an unstructured stack trace **as the tool return value** for those paths).
3. **Automated coverage** — Unit or contract-style tests exercise handlers directly (with replayt available in CI and lightweight fixtures where persistence is involved), including at least one negative case per replayt-touching tool family. Current suite: `tests/test_mcp_tools.py`.
4. **Correlation-aligned errors** — Documented exception and branch inventory for structured errors, **`correlation_id`** on mapped tool errors and the same value in structured stderr logs for the invocation, at least one tested mapped path, and explicit documentation for unmapped exceptions—see [MCP_TOOLS.md § Error response shape](MCP_TOOLS.md#error-response-shape).

## CI and contributor automation

**Intent:** Catch style regressions and test failures **before merge** with the same commands contributors can run locally, clear job logs, and sensible caching for installs.

**Tooling (this repo):** **Ruff** for lint and format (`ruff check`, `ruff format --check`); **pytest** for the test suite under `tests/`. Dev dependencies are declared in `pyproject.toml` (`[project.optional-dependencies] dev` includes Ruff; pytest is listed so a plain editable install can run tests).

**Acceptance criteria (refined, for implementation and review):**

1. **Workflow committed and triggered** — A CI workflow lives under `.github/workflows/` and runs on **pull requests** and **pushes** to the default branch (and matches maintainer conventions for long-lived branches, e.g. `mc/**` on push).
2. **Lint and tests in CI** — Jobs install the package with dev extras, then run **`ruff check`**, **`ruff format --check`**, and **`pytest`**, each as its own step so the first failure is obvious in logs (no need to run later steps if an earlier one fails).
3. **Pip caching** — Use the supported GitHub Actions pattern for **pip cache** keyed on dependency metadata (e.g. `pyproject.toml`) so repeated runs stay fast without hiding install failures.
4. **README documents local commands** — The README states how to run **pytest** and **Ruff** locally (copy-paste or equivalent), including the need for `pip install -e ".[dev]"` when Ruff is required.
5. **CONTRIBUTING states expectations** — [CONTRIBUTING.md](../CONTRIBUTING.md) describes the PR bar: run the same checks as CI (or document a verified equivalent for non-GitHub hosts).
6. **Default branch health** — After the workflow merges, **CI on the default branch stays green** (operational bar for closing the backlog item).

## Replayt minor-line compatibility spike (0.5.x)

**User story:** As a **maintainer**, I want an early **compatibility spike** when replayt publishes **`0.5.x`** so we can widen `pyproject.toml`, adjust pins, and schedule breaking API migrations before integrators are blocked.

**Context:** The declared range today excludes the next pre-1.0 minor line (`<0.5`). When upstream ships **0.5.x**, validate against a **pre-release or GA** artifact, file issues for breaks, and add integrator-facing **CHANGELOG** notes when the range changes.

**Living record:** Findings, rerun commands, API touchpoints, effort guesses, and a **draft migration blurb** for the changelog are maintained in **[REPLAYT_0_5_COMPATIBILITY_SPIKE.md](REPLAYT_0_5_COMPATIBILITY_SPIKE.md)**.

**Refined acceptance criteria (for PRs that actually widen support):**

1. **Recorded findings** — Pass/fail summary against replayt **0.5.x** (exact version, wheel/sdist if relevant, date).
2. **Change list** — Required code or documentation edits with **rough effort** and suggested order.
3. **If widening the range** — Update **`pyproject.toml`**, **README** compatibility table, **`replayt-floor`** pin and job label in **CI**, **`test_version_contract_docs.py`** (`_EXPECTED_REPLAYT_SPEC`), prose in **DESIGN_PRINCIPLES** / **MCP_TOOLS** / **ARCHITECTURE** that quotes the range, optional **reference doc** refresh, and **CHANGELOG** migration text. Work may be **split across follow-up PRs**.

## Audience

| Audience | Needs |
| -------- | ----- |
| **Maintainers** | This mission, scripts, pinned versions, release notes |
| **Integrators** | Stable adapter surface, compatibility expectations |
| **Contributors** | README, [CONTRIBUTING.md](../CONTRIBUTING.md), tests, coding expectations |
