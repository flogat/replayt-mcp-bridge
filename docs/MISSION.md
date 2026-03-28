# Mission: MCP tool bridge for replayt workflow steps

This repository is a **consumer** of [replayt](https://pypi.org/project/replayt/): it adapts replayt-oriented workflow
steps for hosts that speak the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/). It is not a fork of
replayt. Version pins, compatibility shims, and CI live **here**.

**Primary pattern:** **Bridge** — this repository is the **framework bridge** (versus **core-gap**, **LLM showcase**, or **combinator**) that adapts replayt workflow steps for MCP hosts while replayt remains upstream for workflow semantics, as recorded under [Framework bridge](REPLAYT_ECOSYSTEM_IDEA.md#3-framework-bridge) and [Your choice](REPLAYT_ECOSYSTEM_IDEA.md#your-choice) in [REPLAYT_ECOSYSTEM_IDEA.md](REPLAYT_ECOSYSTEM_IDEA.md).

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

**Concrete tool → replayt mapping (living inventory):** Which installed **replayt** entry points each MCP tool uses
(workflow load/contract/dry-run paths, persistence reads, version helpers, etc.) is maintained in
[MCP_TOOLS.md](MCP_TOOLS.md) under **Mapping: tool → replayt capability**. That mapping is the authoritative list for
integrators; this mission section stays pattern-level so it does not drift when tools are added or renamed.

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

## Spec gate checklist (MISSION.md)

Maintainers use this list when closing backlog work on this document (single source of truth for scope):

- No unfilled pattern-selection placeholder block in this file; ecosystem pattern options and the recorded choice live in [REPLAYT_ECOSYSTEM_IDEA.md](REPLAYT_ECOSYSTEM_IDEA.md).
- The **Primary pattern** line is **one sentence**, names **bridge** (versus **core-gap**, **LLM showcase**, **combinator**), and links [Framework bridge](REPLAYT_ECOSYSTEM_IDEA.md#3-framework-bridge) and [Your choice](REPLAYT_ECOSYSTEM_IDEA.md#your-choice) in [REPLAYT_ECOSYSTEM_IDEA.md](REPLAYT_ECOSYSTEM_IDEA.md).
- [README.md](../README.md) keeps **`docs/MISSION.md`** in the first ~30 lines (first screenful) so scope and non-goals are discoverable without scrolling.
- **No draft-prompts placeholder** — There is no “draft prompts” or other stub section left to fill; narrative sections above are the copy-of-record for this item.

### Backlog traceability: “Lock mission, primary pattern, and non-goals in MISSION.md”

**Original backlog acceptance criteria:**

1. MISSION.md has no placeholder draft section.
2. Primary pattern (core-gap / showcase / bridge / combinator) is stated in one sentence.
3. README links to MISSION.md in the first screenful.

Close the tracker when these three hold **and** the four bullets in **Spec gate checklist** above hold—the checklist
makes (2) testable (explicit **bridge** vs named alternatives, both [REPLAYT_ECOSYSTEM_IDEA.md](REPLAYT_ECOSYSTEM_IDEA.md)
anchors), adds the **README** ~30-line discoverability bar, and adds the **tool → replayt** inventory pointer to
[MCP_TOOLS.md](MCP_TOOLS.md) under **What replayt provides**.

## Security and trust boundaries

**Deployment / transport:** How you run the MCP server (stdio, HTTP/SSE, etc.) determines who can reach it; bind
listeners, authentication, and network exposure to a threat model that matches where the bridge runs.

**MCP clients:** Any host the operator connects can invoke registered tools; keep the tool surface small, document side
effects (filesystem, network, subprocesses), and align exposure with organizational access policy.

**Secrets:** Do not embed API keys, tokens, or private paths in code or committed defaults; document required environment
variables and logging/redaction expectations for integrators in **[SECURITY.md](SECURITY.md)** (see also **LLM / demos** below). For **normative acceptance criteria** on spawning the bridge with a **minimal inherited environment** (high-assurance hosts), see [Minimal environment for high-assurance hosts (backlog spec)](#minimal-environment-for-high-assurance-hosts-backlog-spec) below; the shipped operator copy-of-record for examples and variable lists will live in **[SECURITY.md](SECURITY.md)** once implemented.

**Inputs:** Validate and normalize tool arguments at this bridge’s boundary; avoid passing untrusted strings into shells,
dynamic code execution, or paths outside documented intent.

**Bridge tools (security review):** The current server uses **stdio only** (no bridge-owned network listener). Tool handlers do **not** spawn shells or pass arguments through a system shell; strings go to replayt APIs and `pathlib` as documented in [MCP_TOOLS.md](MCP_TOOLS.md). A **`target`** string has the **same implications as the replayt CLI** (`load_target`): it can cause **Python module import** and **workflow file reads** for paths the server process can access—treat it as **trusted operator input**, not anonymous MCP input. **`store_hint`** (legacy path or optional typed `file:` / `jsonl-dir:` / `jsonl:` / `sqlite:` prefix per [MCP_TOOLS.md](MCP_TOOLS.md#store_hint-grammar)) is resolved with `expanduser` and used for **read-only** JSONL directories or SQLite files; it can read any path the process may open, so scope who may attach MCP clients. **`run_id`** is validated via replayt’s store helper before reads. **`persistence_list_run_events`** returns stored event JSON **pass-through by default**; integrators may pass **`event_fields`** or set **`REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`** (see [SECURITY.md](SECURITY.md)) to keep **only listed top-level keys** on each object-shaped event (**before** any optional redaction step). Operators may set **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`** (truthy per [SECURITY.md](SECURITY.md)) so the bridge applies key-based redaction to **`events`** on the MCP result. Top-level filtering does **not** remove nested secrets under retained keys unless redaction applies; payloads may still contain sensitive data—integrators should combine controls, restrict tool access, and read [ARCHITECTURE.md § Optional top-level event field allowlist](ARCHITECTURE.md#architecture-review-optional-top-level-event-field-allowlist) for layering. Expected failures map to structured `{ status: error, tool, replayt_surface, message, correlation_id }` objects without Python tracebacks in the return value for the covered paths; the same **`correlation_id`** appears in matching stderr logs—see [MCP_TOOLS.md § Error response shape](MCP_TOOLS.md#error-response-shape). **Unhandled exceptions** from replayt or the workflow under inspection may still surface according to the MCP host/SDK behavior when they fall **outside** the mapped inventory; stderr still records **`replayt_mcp_bridge.tool.unhandled_exception`** with the same **`correlation_id`** as **`tool.begin`** for operator triage—see [SECURITY.md § Structured tool errors vs unhandled exceptions](SECURITY.md#structured-tool-errors-vs-unhandled-exceptions), [MCP_TOOLS.md § Backlog spec: narrower unhandled-error mapping](MCP_TOOLS.md#backlog-spec-narrower-unhandled-error-mapping-replayt-and-sdk), and [ARCHITECTURE.md § Architecture review: correlation IDs and narrower unhandled-error mapping](ARCHITECTURE.md#architecture-review-correlation-ids-and-narrower-unhandled-error-mapping). For a line-by-line handler pass and residual risks, see [Security review (phase 6)](ARCHITECTURE.md#security-review-phase-6) in [ARCHITECTURE.md](ARCHITECTURE.md).

## Minimal environment for high-assurance hosts (backlog spec)

**Backlog title:** **Publish minimal-environment invocation guidance for high-assurance hosts**

**User story:** As a **security reviewer**, I want a **short, actionable pattern** for spawning the bridge with a **stripped environment** so **inherited provider keys**, **hook commands**, and **accidental secrets** are less likely to be visible to replayt code paths than when launching from a fat desktop shell.

**Intent:** **Documentation-only** in this backlog: add a dedicated subsection to **[SECURITY.md](SECURITY.md)** (not a new top-level doc) and link it from the README **Security, secrets, and MCP hosting** block. The section teaches **process environment** hygiene; it does **not** change bridge code, env parsing, or MCP contracts.

**Placement (normative for Builder):**

- Add a new **`##`-level heading** in `docs/SECURITY.md` (suggested slug-friendly title: **Minimal environment inheritance** or equivalent). Place it **after** [Environment variables](SECURITY.md#environment-variables) (or immediately after its credential / proxy subsections) so readers already understand **`REPLAYT_*`**, **`REPLAYT_MCP_BRIDGE_*`**, and provider keys before seeing spawn recipes.
- In [README.md](../README.md) under **## Security, secrets, and MCP hosting**, add **one sentence** plus an anchor link to that new heading (same style as existing `docs/SECURITY.md#mcp-tool-capability-tiers` links). The link **must** use a path under `docs/SECURITY.md` with the correct fragment for the chosen heading.

**Content requirements (normative):**

1. **State the trust surface in one place** — The Python process **inherits the full OS environment** (already stated elsewhere in SECURITY); restate briefly that **replayt** may read **hook argv** from env (commands or argv strings), **policy-hook JSON** from env, **provider / LLM** variables, and **standard credential names** (see [Credentials and LLM / API access (replayt)](SECURITY.md#credentials-and-llm--api-access-replayt) and `LLM_CREDENTIAL_ENV_VARS` in upstream **`replayt.security`**). **Bridge-owned** knobs remain **`REPLAYT_MCP_BRIDGE_*`** as in [Environment variables](SECURITY.md#environment-variables).
2. **Hook-related replayt variables (must be named explicitly)** — The shipped doc **must** call out at least these **upstream** env vars (names only; do not paste real hook commands or secrets in examples):
   - **`REPLAYT_RUN_HOOK`**, **`REPLAYT_RESUME_HOOK`**, **`REPLAYT_EXPORT_HOOK`**, **`REPLAYT_SEAL_HOOK`**, **`REPLAYT_VERIFY_SEAL_HOOK`** (hook argv sources per replayt **`run_support` / `config_cmd`**).
   - Matching **`*_TIMEOUT`** siblings where replayt documents them (**`REPLAYT_RUN_HOOK_TIMEOUT`**, **`REPLAYT_RESUME_HOOK_TIMEOUT`**, **`REPLAYT_EXPORT_HOOK_TIMEOUT`**, **`REPLAYT_SEAL_HOOK_TIMEOUT`**, **`REPLAYT_VERIFY_SEAL_HOOK_TIMEOUT`**).
   - **`REPLAYT_POLICY_HOOK_CONTEXT_JSON`** and **`REPLAYT_POLICY_HOOK_NAME`** (policy-hook subprocess context).
   - Cross-link or align with the existing short row for **`REPLAYT_POLICY_HOOK_CONTEXT_JSON`** and the ellipsis row for **`REPLAYT_RUN_HOOK`**, **`REPLAYT_RESUME_HOOK`**, … in the [Variables that commonly affect this bridge](SECURITY.md#variables-that-commonly-affect-this-bridge) table—avoid contradicting that table; extend it if the new section introduces additional names not already listed.
3. **Two operator profiles** — Provide a **compact table or bullet lists** contrasting:
   - **Local dev / full-fat shell** — Typical case: inherited desktop env; may include **`OPENAI_API_KEY`**, **`REPLAYT_PROVIDER`**, **`REPLAYT_MODEL`**, hooks, **`REPLAYT_LOG_DIR`**, etc.; acceptable when the MCP parent and workstation match the threat model.
   - **Read-only introspection / high-assurance spawn** — Goal: run **`replayt_version_info`**, **`workflow_contract_snapshot`**, **`workflow_graph_mermaid`**, **`runner_dry_run_plan`**, and similar paths **without** LLM credentials and **without** hook commands in env. List categories of variables the operator **should unset or omit** (provider keys, hook argv, policy-hook JSON, optional proxy vars if egress must be denied) vs **minimal variables often still required** for a working **`python`** / **`PATH`** / **`HOME`** (or Windows equivalents) and any **explicit** `REPLAYT_MCP_BRIDGE_*` or **`REPLAYT_LOG_DIR`** the operator chooses to set. Call out that **exact minimal sets are OS- and install-dependent**—examples are illustrative.
4. **POSIX example** — At least one **copy-paste-oriented** example using a **clean slate** pattern (e.g. `env -i` **or** `sudo -E` / systemd `Environment=` with an explicit allowlist—pick one primary pattern and explain it). Show passing **`PATH`** (and **`HOME`** if needed) so `python` resolves; show invoking **`python -m replayt_mcp_bridge`** or **`replayt-mcp-bridge`**. Use **placeholder** values only (`/usr/bin`, `/opt/venv/bin/python`, etc.).
5. **Windows example** — At least one example for **cmd.exe** or **PowerShell** that achieves the **same intent** (replace inherited env with a small allowlist or clear sensitive names). Note **WSL** vs native Windows differences in one sentence if examples are POSIX-centric.
6. **Honest limits (“does not fix”)** — A dedicated short subsection **must** state that stripping the environment **does not**:
   - Remove **filesystem** access to secrets (**`.env`**, **`.replaytrc.toml`**, **`pyproject.toml`** `[tool.replayt]`, workflow files, JSONL/SQLite stores)—replayt and the bridge still read config from disk per project layout.
   - Prevent **import-time** or **tool** side effects from a malicious **`target`** or readable workflow (same as [Security and trust boundaries](#security-and-trust-boundaries)).
   - Replace **host-side tool policy**, **MCP client logging** controls, or **network** egress policy; combine with [Host-side partial tool exposure](SECURITY.md#host-side-partial-tool-exposure) and [MCP host and client logs](SECURITY.md#mcp-host-and-client-logs).
   - Guarantee absence of secrets in **memory** if other processes share the address space or debuggers attach—scope is **inherited env of the child process**, not full OS isolation.

**Original backlog acceptance criteria (traceability):**

1. New subsection in **`docs/SECURITY.md`** linked from the README security callout.
2. Explicitly calls out **hook-related replayt env vars** and **provider keys** as inherited trust surface.
3. **No false claims** — states what stripping does **not** fix (e.g. filesystem access to **`.env`** files).

**Acceptance criteria (refined, for implementation and review — Builder / Tester):**

1. **`docs/SECURITY.md`** contains the new section with **POSIX** and **Windows** examples, the **two profiles**, **hook** and **credential** callouts, and the **does not fix** list above.
2. **`README.md`** includes an anchor link to the new section from **## Security, secrets, and MCP hosting** (first ~45 lines remain consistent with [`tests/test_security_docs.py`](../tests/test_security_docs.py) expectations for SECURITY discoverability unless the test window is intentionally updated in the same change-set).
3. **Wording** stays consistent with [Environment variables](SECURITY.md#environment-variables) (full inheritance, replayt + bridge vars).
4. **Changelog** — Add an **Unreleased** bullet in [CHANGELOG.md](../CHANGELOG.md) when the user-facing doc ships (Builder commit); this spec-only phase does not require a changelog entry.

**Implementation status:** **Not shipped** — spec recorded here for phase **3** (Builder).

### Backlog traceability: “Publish minimal-environment invocation guidance for high-assurance hosts”

**Close the tracker when:** the four bullets under **Acceptance criteria (refined, for implementation and review)** above hold **and** the three **Original backlog acceptance criteria** bullets remain satisfied in the tree.

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

## One-shot operator health check (install probe)

**Backlog title:** **Add a one-shot server health command for operators**

**User story:** As an **operator** automating deploy checks, I want **`replayt-mcp-bridge`** (or **`python -m replayt_mcp_bridge`**) to support a **non-interactive** mode that verifies **imports**, **logging setup**, and **replayt version visibility**, then **exits 0**, so scripts can probe installs **without** holding stdio open for a long-running MCP server.

**Intent:** Long-running stdio servers are awkward in health probes (Kubernetes `exec`, CI sanity checks, post-install scripts). A **single discoverable subcommand** on the **same packaged entrypoints** as the MCP server keeps automation aligned with how hosts already launch the bridge.

**Non-goals:** This is **not** a substitute for full MCP integration tests (handshake, `tools/list`, `tools/call`)—those remain covered by [`tests/test_mcp_stdio_session_smoke.py`](../tests/test_mcp_stdio_session_smoke.py) and related modules.

**Recommended CLI shape (refined):**

- **Primary interface:** a **`health`** subcommand on both **`python -m replayt_mcp_bridge`** and the **`replayt-mcp-bridge`** console script (e.g. **`python -m replayt_mcp_bridge health`**, **`replayt-mcp-bridge health`**). A **global flag** alternative (e.g. **`--health-check`**) is acceptable only if it stays **mutually exclusive** with default stdio-server behavior and is documented beside the subcommand.
- **Behavior:** run **before** entering the FastMCP stdio loop; perform the checks below; write **human-readable** status to **stderr** (and optionally **one** structured JSON line compatible with [`observability.py`](../src/replayt_mcp_bridge/observability.py) conventions for operators who parse logs); **exit 0** on success.
- **Checks (minimum):** (1) **Bridge import** — `import replayt_mcp_bridge` (and any minimal `server` / `observability` surface needed for the probe). (2) **Replayt import and version** — import **`replayt`** successfully and report the same resolved version string (or tuple) as **`replayt_version_info`** / `installed_replayt_version` helpers in [`server.py`](../src/replayt_mcp_bridge/server.py), so the probe proves the **declared dependency range** is satisfiable at runtime. (3) **Logging setup** — call **`configure_bridge_logging()`** (or an extracted shared helper) once and emit at least one **INFO**-level line so deploy scripts can confirm stderr logging works (without starting MCP).

**Critical failures (nonzero exit, refined):**

- **`ImportError`** or **`ModuleNotFoundError`** for **`replayt`** or **`replayt_mcp_bridge`** (missing / broken install).
- **Unexpected errors** while resolving the replayt version (treat as **critical** so “silent unknown version” does not pass CI).
- **Logging configuration failure** if the implementation defines configuration errors as **fatal** for the probe (document the choice in README).

**Out of scope for “critical” (unless later expanded and documented):** MCP transport readiness, workflow **target** resolution, persistence paths, and optional **`REPLAYT_MCP_BRIDGE_*`** env semantics—the health command validates **packaging + core imports + observability bootstrap**, not full tool contracts.

**Acceptance criteria (refined, for implementation and review):**

1. **README** — Documents the **exact** invocation(s) (`health` subcommand and console-script parity); states **exit codes** (0 success, nonzero on the critical failures above); points to this section for rationale and non-goals.
2. **Nonzero on critical failures** — Implementation exits **nonzero** when replayt (or the bridge) cannot be imported or version resolution fails per the table above; document any additional **critical** cases explicitly.
3. **Pytest without MCP host** — Tests assert **exit codes** by spawning **`sys.executable`** with **`-m replayt_mcp_bridge health`** (and optionally the console script) in a **subprocess**—**no** MCP client, **no** JSON-RPC session. Include at least: **happy path** → exit **0**; **one negative path** that proves nonzero exits without relying on a real MCP host (for example a **monkeypatched** or **isolated** import failure **or** a documented test helper that simulates a missing dependency—choose an approach that stays **reliable in CI**).

**Implementation status (shipped):** The probe is live on both packaged entrypoints; **[README.md](../README.md)** is the operator copy-of-record for exact invocations and the **0 / 1 / 2** exit-code table. Implementation: [`health_probe.py`](../src/replayt_mcp_bridge/health_probe.py); tests: [`test_cli_health.py`](../tests/test_cli_health.py).

Architecture layering and traceability are recorded under [ARCHITECTURE.md § Architecture review: one-shot operator health check (install probe)](ARCHITECTURE.md#architecture-review-one-shot-operator-health-check-install-probe).

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

- Run inside the **default** CI test job (**`pytest -q -m "not network"`** on Linux **`test`**, **`test-windows`**, and **`replayt-floor`**—same install as other tests), with an explicit **per-test timeout** in the tens-of-seconds range so a broken server cannot hang the job.
- Prefer the **official MCP Python SDK** **client** running **in the pytest process**: `ClientSession` with `stdio_client`, launching the bridge via `StdioServerParameters` using **`sys.executable`** and **`["-m", "replayt_mcp_bridge"]`** (or the installed console script) and **`cwd`** at the repository root—aligned with [MCP_HOST_CONFIG.md](MCP_HOST_CONFIG.md) and [ARCHITECTURE.md](ARCHITECTURE.md#process-and-transport). **Await handshake / session setup and the tool round-trip** instead of using fixed **`sleep()`** delays for readiness.
- **Happy-path tool:** Prefer **`replayt_version_info`** (proves replayt import and structured success through the full stack). **`replayt_echo`** is an acceptable alternative when the goal is **MCP wiring only**; document the choice in the test module.

**Acceptance criteria (refined, for implementation and review):**

1. **Default CI** — The new test module is collected and run by the standard **`pytest -q -m "not network"`** step in `.github/workflows/ci.yml` (no extra job required unless maintainers later choose to split slow tests). Tests marked **`network`** stay opt-in; see [CONTRIBUTING.md](../CONTRIBUTING.md).
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
2. **Lint and tests in CI** — Jobs install the package with dev extras, then run **`ruff check`**, **`ruff format --check`**, and **`pytest -q -m "not network"`**, each as its own step so the first failure is obvious in logs (no need to run later steps if an earlier one fails).
3. **Pip caching** — Use the supported GitHub Actions pattern for **pip cache** keyed on dependency metadata (e.g. `pyproject.toml`) so repeated runs stay fast without hiding install failures.
4. **README documents local commands** — The README states how to run **pytest** and **Ruff** locally (copy-paste or equivalent), including the need for `pip install -e ".[dev]"` when Ruff is required.
5. **CONTRIBUTING states expectations** — [CONTRIBUTING.md](../CONTRIBUTING.md) describes the PR bar: run the same checks as CI (or document a verified equivalent for non-GitHub hosts).
6. **Default branch health** — After the workflow merges, **CI on the default branch stays green** (operational bar for closing the backlog item).

**Single local entrypoint:** Prefer **`python scripts/run_ci_checks.py`** after **`pip install -e ".[dev]"`** for **argv parity** with the default test jobs—see [Single local check entrypoint (contributor CI parity)](#single-local-check-entrypoint-contributor-ci-parity).

## Single local check entrypoint (contributor CI parity)

**Backlog title:** **Provide a single local check entrypoint for contributors**

**User story:** As a **new contributor**, I want **one command** that runs the **same** **Ruff** and **pytest** sequence as the **default CI test jobs** so I do not have to copy three shell lines from the README.

**Intent:** A **thin wrapper** may coexist with **copy-paste** documentation in [README.md](../README.md) and [CONTRIBUTING.md](../CONTRIBUTING.md). Normative parity is **subprocess argument vectors** and **ordering** for lint + default pytest, aligned with **`.github/workflows/ci.yml`**.

**Canonical invocation (implemented):** From the **repository root**, with **`pip install -e ".[dev]"`** already applied to the **active** interpreter / venv:

```bash
python scripts/run_ci_checks.py
```

**Normative step list (must match the Linux `test` job’s Ruff + pytest run lines):**

1. **`ruff check src tests`**
2. **`ruff format --check src tests`**
3. **`pytest -q -m "not network"`**

Those are the same three **run** steps used in the **`test`**, **`test-windows`**, and **`replayt-floor`** jobs for lint and tests (Windows uses the same argv; **`replayt-floor`** adds a prior **`pip install --force-reinstall "replayt==0.4.25"`** step that the wrapper does **not** duplicate).

**Explicit non-scope (normative):** The default local entrypoint does **not** run **`pip-audit`** (the **`supply-chain`** job), does **not** reinstall a floor **replayt** pin, and does **not** substitute for a full **GitHub Actions** matrix (multiple Python minors). Contributors follow [CONTRIBUTING.md](../CONTRIBUTING.md) and [DEPENDENCY_AUDIT.md](DEPENDENCY_AUDIT.md) for **supply-chain** reproduction.

**Tooling versions:** **Ruff** must come from the environment produced by **`pip install -e ".[dev]"`** so it resolves per **`[project.optional-dependencies] dev`** in **`pyproject.toml`** (same as CI install steps). **pytest** is declared under **`[project].dependencies`**; the wrapper invokes the **`pytest`** on **`PATH`** from that environment.

**Behavior (normative):**

- **Fail-fast** — After each step, if the subprocess returns **nonzero**, the wrapper **exits immediately** with that return code (or **1** when no code is available—implementations should document the choice; today [`scripts/run_ci_checks.py`](../scripts/run_ci_checks.py) returns **`1`** only when **`returncode` is `None`**).
- **Working directory** — **Repository root**, so relative paths **`src`** and **`tests`** match CI.
- **Portability** — The documented command uses **`python …`** only (no POSIX-only shell features required for the **default** path), so it is **feasible on Windows and Unix** with the same venv story as [CONTRIBUTING.md](../CONTRIBUTING.md).

**Automation / regression guard:** [`tests/test_version_contract_docs.py`](../tests/test_version_contract_docs.py) **`test_run_ci_checks_script_matches_ci_test_job_steps`** asserts that **`scripts/run_ci_checks.py`** **`CI_CHECK_STEPS`** stays aligned with the **Linux `test`** job’s **`ruff` / `pytest`** **run** lines in **`.github/workflows/ci.yml`**. When CI changes those steps, update **the script and the test** in the **same** change-set.

**Acceptance criteria (refined, for implementation and review):**

1. **CONTRIBUTING is copy-of-record** — [CONTRIBUTING.md](../CONTRIBUTING.md) names **`python scripts/run_ci_checks.py`** as the **preferred** one-shot check (after **`pip install -e ".[dev]"`**) and states that it matches the **Ruff** + **pytest** subprocesses in the **`test`**, **`test-windows`**, and **`replayt-floor`** jobs.
2. **README cross-link** — [README.md](../README.md) **Local checks** (or equivalent) points contributors at that command and optionally at this section (recommended for discoverability).
3. **Argv parity** — The wrapper runs the **same** **`ruff`** and **`pytest`** argument lists—in **order**—as the Linux **`test`** job steps above (**`src`**, **`tests`**, marker **`not network`**).
4. **First failure wins** — First failing step yields a **nonzero** process exit; all steps passing yields **0**.
5. **Windows + Unix** — The documented invocation works on **Windows** and **Unix** where **`python`** is the same interpreter used for **`pip install -e ".[dev]"`** (see [Windows CI runner (install and pytest smoke)](#windows-ci-runner-install-and-pytest-smoke) for CI signal on **`windows-latest`**).
6. **Drift detection** — A **contract test** (today **`test_run_ci_checks_script_matches_ci_test_job_steps`**) fails if **`CI_CHECK_STEPS`** and **`.github/workflows/ci.yml`** diverge.

**Implementation status (shipped):** [`scripts/run_ci_checks.py`](../scripts/run_ci_checks.py); contributor docs in [CONTRIBUTING.md](../CONTRIBUTING.md) and [README.md](../README.md); this section is the **normative** scope and parity definition for the backlog item.

### Backlog traceability: “Provide a single local check entrypoint for contributors”

**Original acceptance criteria:**

- Documented command in **CONTRIBUTING.md** (README optional cross-link).
- Wrapper exits **nonzero** on first failing step; works on **Windows** and **Unix** where feasible.
- Must invoke the **same** **Ruff** and **pytest** arguments **CI** uses; version pins follow **`pyproject.toml`** **dev** extra (and base deps for **pytest**).

**Close the tracker when:** **(1–6)** above hold **and** the **original** bullets remain true after any CI or script change (update **script + contract test + docs** together when **`ci.yml`** steps change).

## CI dependency vulnerability scanning (supply-chain)

**Backlog title:** **Add CI dependency vulnerability scanning for direct runtime deps**

**User story:** As a **maintainer**, I want **CI** to surface **known vulnerabilities** in the **Python packages this bridge installs** (including **replayt**, **mcp**, and their transitive dependencies) so supply-chain issues are noticed **before merge**, without claiming **compliance certification** or **exhaustive** assurance.

**Intent:** Complement manual pin reviews with a **lightweight, reproducible** audit step that uses the **same lock-free `pyproject.toml` resolution** CI already exercises: install the package, then run **[PyPA pip-audit](https://pypi.org/project/pip-audit/)** (or a **documented equivalent** only if maintainers replace the tool in the same change-set). The scan targets the **resolved environment** after **`pip install -e ".[dev]"`**—that includes **`[project].dependencies`** and **transitive** wheels, plus **dev** tools (**Ruff**, **pip-audit**, etc.), because that matches what contributors and **`supply-chain`** matrix jobs actually install.

**Non-goals:** This is **not** a substitute for organizational **SBOM**, **penetration testing**, or **legal** “clean bill of health” language. **No committed full lockfile** is required unless the team **explicitly** adopts that model in the same change-set (this repo stays **range-based** in `pyproject.toml` by default).

**Documented command (canonical for CI and local parity):** After `pip install -e ".[dev]"`:

```bash
pip-audit --ignore-vuln CVE-2026-4539 --desc
```

**Severity / gating policy:** **pip-audit** does **not** expose a **`--severity-high`** (or similar) gate in the versions we use. The **effective policy** is: **any** reported vulnerability **fails** the job **unless** it is **documented** as an accepted risk in **[DEPENDENCY_AUDIT.md](DEPENDENCY_AUDIT.md)** **and** the same **`--ignore-vuln`** IDs appear in **[`.github/workflows/ci.yml`](../.github/workflows/ci.yml)** so reviewers see **one** audited list. Prefer **upstream fixes** (dependency bumps) over ignores; when upstream has **no** fix, record **CVE/advisory id**, **short rationale**, **revisit trigger**, and a **ticket or issue URL** in **DEPENDENCY_AUDIT.md** (see that file’s template).

**Blocking vs advisory (normative):** The **`supply-chain`** workflow step is **blocking**: a **nonzero** **`pip-audit`** exit fails that job and therefore fails CI for the change. There is **no** separate **advisory-only** (warn-but-green) automation in this repository; introducing one would be an explicit maintainer backlog so policy stays documented.

**Default pytest path vs audit:** Linux **`test`**, **`test-windows`**, and **`replayt-floor`** run **`pytest -q -m "not network"`** only—they do **not** invoke **`pip-audit`**. The vulnerability scan lives in the dedicated **`supply-chain`** job. Contributors matching the **default** local bar (**Ruff** + that **pytest** command) are aligned with those test jobs without running the audit; **[CONTRIBUTING.md](../CONTRIBUTING.md)** and **[DEPENDENCY_AUDIT.md](DEPENDENCY_AUDIT.md)** state when to run **`pip-audit`** and how it differs from **pytest** (including **network** expectations for advisory lookups).

**Acceptance criteria (refined, for implementation and review):**

1. **Workflow coverage** — [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) defines a **`supply-chain`** job that runs on **pull requests** and **pushes** to the default branch (and **`mc/**`** per existing **`on:`** conventions), on **`ubuntu-latest`**, with the **documented** **`pip-audit`** invocation after **`pip install -e ".[dev]"`** (same flags as [DEPENDENCY_AUDIT.md](DEPENDENCY_AUDIT.md)).
2. **Python matrix alignment** — Unless a backlog explicitly narrows scope, **`supply-chain`** uses the **same CPython minors** as the Linux **`test`** job (**3.11, 3.12, 3.13**) so resolution differences across supported interpreters are visible.
3. **Policy documentation** — [CONTRIBUTING.md](../CONTRIBUTING.md) and **[SECURITY.md](SECURITY.md)** point maintainers at **[DEPENDENCY_AUDIT.md](DEPENDENCY_AUDIT.md)** for **tool choice**, **severity / fail semantics**, **accepted-risk / false-positive** process, and **local reproduction**.
4. **No lockfile mandate** — Closing this backlog does **not** require committing **`requirements.txt`**, **`uv.lock`**, **`poetry.lock`**, or similar unless a **separate** maintainer decision lands in the **same** change-set and is documented in **DEPENDENCY_AUDIT.md** and **CONTRIBUTING.md**.
5. **CONTRIBUTING local reproduction** — [CONTRIBUTING.md](../CONTRIBUTING.md) documents how to reproduce the **`supply-chain`** check locally: **`pip install -e ".[dev]"`** then the **exact** **`pip-audit`** line from **[DEPENDENCY_AUDIT.md](DEPENDENCY_AUDIT.md)** (kept in sync with the workflow; guarded by **`tests/test_version_contract_docs.py`**).
6. **Blocking vs advisory documented** — **[DEPENDENCY_AUDIT.md](DEPENDENCY_AUDIT.md)** and the **`supply-chain`** step comment in **`.github/workflows/ci.yml`** make the **blocking** semantics explicit (no silent downgrade to “warnings only” without a doc + workflow change).
7. **Offline-friendly default pytest** — The documented **default** **`pytest -q -m "not network"`** path is **not** wired to **`pip-audit`** (no pytest plugin, no shared step with **`test`** that runs the scanner). **`pip-audit`** remains **CI-only** in the sense of **job separation**; local runs are optional for contributors who cannot reach advisory sources.

**Implementation status (shipped):** **`pip-audit`** is listed under **`[project.optional-dependencies] dev`** in **`pyproject.toml`**; CI job **`supply-chain`** and **[DEPENDENCY_AUDIT.md](DEPENDENCY_AUDIT.md)** are the copy-of-record for flags and ignores. **Windows** jobs intentionally omit this audit—see **[Windows CI runner (install and pytest smoke)](MISSION.md#windows-ci-runner-install-and-pytest-smoke)**.

### Backlog traceability: “Add automated dependency vulnerability scanning to CI”

**Original backlog title:** *Add automated dependency vulnerability scanning to CI* (fail or warn on known vulnerable dependencies; prefer **pip-audit** / Dependency Review / equivalent with allowlist discipline).

**Map to this section:** **pip-audit**, job **`supply-chain`**, and **[DEPENDENCY_AUDIT.md](DEPENDENCY_AUDIT.md)**. Close the tracker when **(1–7)** above hold **and** the original backlog bullets hold: **workflow step** reproducible from **[CONTRIBUTING.md](../CONTRIBUTING.md)** with the **exact** command; **blocking vs advisory** policy explicit in docs and the workflow comment; **default pytest** path stays **decoupled** from **`pip-audit`** so offline contributors can match the test jobs without running the scanner.

## Dependabot (or equivalent) for GitHub Actions pins

**Backlog title:** **Add Dependabot (or equivalent) for GitHub Actions pins**

**User story:** As a **maintainer**, I want **automated pull requests** bumping **`actions/checkout`**, **`actions/setup-python`**, and other **`uses:`** pins in workflow YAML so **supply-chain hygiene** for the **Actions layer** does not rely on **manual audits** alone.

**Intent:** Complement **[CI dependency vulnerability scanning (supply-chain)](#ci-dependency-vulnerability-scanning-supply-chain)** (PyPI / **`pip-audit`**) with **targeted automation for GitHub-hosted action references**. Today [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) pins **`actions/checkout@v4`** and **`actions/setup-python@v5`** across **Linux** and **Windows** jobs; the automation should keep those pins **current** on a **predictable cadence** without spamming unrelated ecosystems.

**Non-goals:**

- **No** **`pip`** / **`npm`** / **Docker** **Dependabot** (or Renovate) ecosystems in the **same** backlog unless maintainers **explicitly** widen scope in the **implementation PR** and record the decision **here** and in **[CONTRIBUTING.md](../CONTRIBUTING.md)**.
- **Not** a replacement for **reading upstream release notes** when a major **Actions** release changes behavior (reviewers still judge **semver** and **breaking** changes).
- **Not** a substitute for **[pip-audit](#ci-dependency-vulnerability-scanning-supply-chain)**—**PyPI** and **Actions** supply-chain signals stay **separate** by design.

**Default implementation shape (normative unless an equivalent is documented):**

- Commit **`.github/dependabot.yml`** (or **`.github/dependabot.yaml`**) using **`version: 2`** with **at least one** `updates` entry where:
  - **`package-ecosystem: "github-actions"`**
  - **`directory: "/"`** (GitHub’s documented convention for workflow files under **`.github/workflows/`**)
- Set **`schedule.interval`** to **`weekly`** unless maintainers choose **`monthly`** for **lower noise**; the **committed file** must state the **effective cadence** (YAML comment or this section stays in sync when the choice changes).
- Prefer **`groups`** (or Dependabot’s **grouping** fields) so **multiple** action bumps can land in **one** PR when that matches **team noise tolerance**; if **ungrouped** PRs are chosen, document **why** (for example **easier bisection**) in the **same** change-set.

**Documented behavior (required):** The **config file** under **`.github/`** must make the following **discoverable without opening GitHub settings**:

- **What** is managed (**GitHub Actions** `uses:` references in this repository’s workflow files).
- **How often** checks run (**schedule**).
- **Whether** updates are **grouped** and any **naming** convention for PR titles (if customized).

YAML **leading comments** satisfy this bar; a short **`.github/DEPENDABOT.md`** (or similar) is optional if comments become unwieldy.

**Acceptance criteria (refined, for implementation and review):**

1. **Committed config** — A **Dependabot v2** config (or a **documented equivalent**, for example **Renovate** with **`github-actions`** enabled and config committed under **`.github/`**) is **merged** and **active** on the repository (Dependabot enabled per **org/repo** policy is a **prerequisite** maintainers verify).
2. **Scope** — Automation targets **only** the **GitHub Actions** ecosystem for **`uses:`** pins (this repo’s **`.github/workflows/*.yml`**). Expanding to **other** ecosystems is **out of scope** unless **(non-goals)** above is updated in the **same** PR.
3. **Discoverable policy** — The **config** (and optional companion note under **`.github/`**) documents **interval**, **grouping** (or explicit **ungrouped** policy), and **what** files are scanned, per **Documented behavior** above.
4. **CONTRIBUTING maintainer note** — [CONTRIBUTING.md](../CONTRIBUTING.md) gains **at least one** short subsection or paragraph that tells maintainers **how Action pin updates arrive** (Dependabot PRs or equivalent), that **green CI** is the **merge bar** unless a change is **intentionally** held, and **where** to read the **full** policy (**this section** + the **`.github/`** config). It should **cross-link** **[pip-audit](#ci-dependency-vulnerability-scanning-supply-chain)** / **[DEPENDENCY_AUDIT.md](DEPENDENCY_AUDIT.md)** so **PyPI** vs **Actions** automation is not conflated.
5. **Operational bar** — After merge, **Dependabot (or equivalent)** is observed to open **at least one** valid PR or **would** open PRs when pins drift (maintainers may **simulate** by temporarily pinning an **older** patch in a throwaway branch if needed); **no** requirement to merge a bot PR in the **same** change-set as the config **unless** the team chooses to.

**Implementation status (shipped):** **`.github/dependabot.yml`** is committed (**`github-actions`**, **`directory: "/"`**, **weekly** schedule, **grouped** updates under **`github-actions`**). Maintainer process lives in **[CONTRIBUTING.md](../CONTRIBUTING.md)**. **Org/repo** must still allow Dependabot version updates (or maintainers use a documented equivalent such as Renovate).

### Backlog traceability: “Add Dependabot (or equivalent) for GitHub Actions pins”

**Original acceptance criteria:** (1) Config under **`.github/`** with **documented behavior**; (2) **CONTRIBUTING.md** maintainer note on **how updates are handled**.

**Map to this section:** **`.github/dependabot.yml`** (or **equivalent**), **[CONTRIBUTING.md](../CONTRIBUTING.md)** cross-links, and **(1–5)** above. Close the tracker when the **original** bullets hold **and** **scope** stays **GitHub Actions**-only unless **explicitly** expanded with doc updates.

## GitHub issue templates (integration vs bridge-defect reports)

**Backlog title:** **Add GitHub issue templates for integration vs bridge-defect reports**

**User story:** As a **reporter**, I want **guided GitHub issue forms** that ask for **MCP host**, **bridge and replayt versions**, and **redacted** configuration snippets, so **maintainers** can triage **bridge defects** separately from **host / integration** noise with less back-and-forth.

**Intent:** Ship **two** distinct **[issue forms](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms)** under **`.github/ISSUE_TEMPLATE/`** (YAML with **`body`** + front matter). Each template’s **description** and/or **markdown** blocks should **link** **[docs/SECURITY.md](SECURITY.md)** (logging, redaction, what not to paste) and **[CONTRIBUTING.md](../CONTRIBUTING.md)** (checks, scope, how to run the same pytest/Ruff bar locally). Optionally add **`.github/ISSUE_TEMPLATE/config.yml`** to tune **blank issues** and **contact links**—not required for acceptance unless maintainers want a single entry screen.

**Non-goals:** No **runtime** bridge code, **pytest**, or **CI workflow** changes are required for this backlog item (templates and docs only). **Security embargo** process (if any) stays outside this spec—templates still **remind** readers of **[docs/SECURITY.md](SECURITY.md)**.

### Template split (normative)

| Template | Audience / when to use | Primary maintainer question |
| -------- | ---------------------- | ---------------------------- |
| **Bridge bug** (working name; slug SHOULD be readable, e.g. **`bridge-bug.yml`**) | Regressions or incorrect behavior in **this repository’s** MCP bridge (**handlers**, **packaging**, **documented tool contracts**, **tests** that ship here) | “Is this a defect in **replayt-mcp-bridge** (or its tests/docs) on a **supported** matrix?” |
| **Integration / host** (e.g. **`integration-host.yml`**) | **MCP client / IDE** wiring, **launch config**, **stdio** attachment, **permissions**, **environment** on the operator side—often “works in a terminal but not in the host” | “Is this a **host configuration** or **trust-boundary** problem rather than bridge logic?” |

Each file MUST use GitHub’s issue-form syntax: top-level keys such as **`name`**, **`description`**, optional **`title`**, optional **`labels`**, and a **`body`** list of **`type: markdown`**, **`input`**, **`textarea`**, **`dropdown`**, etc., as appropriate.

### Fields and copy (minimum bar)

**Both** templates MUST:

1. **MCP host** — Ask for **product name** and **version** (or “unknown”) of the MCP client / IDE hosting the server (e.g. Cursor, Claude Desktop, Zed, custom).
2. **Versions** — Ask for **replayt-mcp-bridge** / package version and **replayt** version, and point reporters to **at least one** of: **`pip show replayt-mcp-bridge`**, **`pip show replayt`**, **`python -m replayt_mcp_bridge health`** (stderr + exit **0** on success), or the **`replayt_version_info`** tool over MCP—consistent with **[README.md](../README.md)** and **[MCP_TOOLS.md](MCP_TOOLS.md)**. **Python** version (`python --version`) SHOULD be requested when relevant to reproducing install issues.
3. **Secrets and logs** — Explicitly tell reporters **not** to paste API keys, tokens, private URLs with credentials, full environment dumps, or **unredacted** persistence / tool payloads; point to **[docs/SECURITY.md](SECURITY.md)** (**especially [MCP host and client logs](SECURITY.md#mcp-host-and-client-logs)** and any related subsections maintainers rely on).
4. **Doc links** — Visible links (markdown blocks or `description` text) to **`docs/SECURITY.md`**, **`CONTRIBUTING.md`**, and (for the integration template) **`docs/MCP_HOST_CONFIG.md`** using **repository-relative** paths so they resolve in the GitHub web UI.

**Integration / host** template SHOULD additionally ask for a **redacted** snippet of **MCP server config** (e.g. `command` / `args` shape with **placeholder** env values), **working directory** / `cwd` if known, and cross-link **[MCP_HOST_CONFIG.md](MCP_HOST_CONFIG.md)** for stdio-oriented examples.

**Bridge bug** template SHOULD ask for **expected vs actual** behavior, **steps to reproduce**, and—when a structured tool error was returned—the **`correlation_id`** (and remind reporters **not** to paste full stderr if it contains sensitive paths—summarize or redact per **[docs/SECURITY.md](SECURITY.md)**).

### Acceptance criteria (refined, for implementation and review)

1. **Two YAML issue forms** live under **`.github/ISSUE_TEMPLATE/`**, matching the **Bridge bug** vs **Integration / host** split above (filenames are implementer choice; content MUST match intent).
2. **Both** reference **where to read versions** (commands / tools above) and **both** warn **not** to paste secrets; **both** link **SECURITY** and **CONTRIBUTING** as in the **Intent** paragraph.
3. **No runtime code** changes are required to close this backlog item (docs + templates only).

### Backlog traceability

**Original acceptance criteria:** (1) At least **two** templates—**Bug** (bridge) and **Integration / host**; (2) both reference version info and no-secrets guidance; (3) no runtime code required.

**Map to this section:** **`.github/ISSUE_TEMPLATE/*.yml`**, links to **`docs/SECURITY.md`** / **`CONTRIBUTING.md`**, and **(1–3)** above. Close the tracker when the **original** bullets hold **and** the **minimum field bar** (host, versions, secrets, doc links) is satisfied in **both** forms.

## Windows CI runner (install and pytest smoke)

**User story:** As a **Windows-first developer**, I want **CI** to prove **`pip install -e ".[dev]"`** and the **test suite** on a **Windows** image, because local docs already call out **WinError** and **`Scripts\`** edge cases for console scripts.

**Intent:** Add **one** job on **`windows-latest`** with **CPython 3.12**, matching the Linux **`test`** job’s **install → Ruff → `pytest -q -m "not network"`** sequence and **pip** cache keyed on **`pyproject.toml`**, so CI catches path separators, entry points, and encoding issues common on Windows MCP hosts.

**Non-goals:** No extra **Python** matrix on Windows (cost and complexity). **`replayt-floor`** and **`supply-chain`** stay **Linux-only** unless a new backlog says otherwise.

**Acceptance criteria (refined, for implementation and review):**

1. **[.github/workflows/ci.yml](../.github/workflows/ci.yml)** defines a dedicated Windows test job (for example **`test-windows`**) on **`windows-latest`** with a single pinned minor (**3.12**).
2. That job runs **`pip install -e ".[dev]"`**, **`ruff check`**, **`ruff format --check`**, and **`pytest -q -m "not network"`** on **`src`** / **`tests`** (same commands as the Linux **`test`** job), unless maintainers document a **deliberate** split with equivalent coverage.
3. **`actions/setup-python`** enables **pip** caching with **`cache-dependency-path`** (or equivalent) tied to dependency metadata such as **`pyproject.toml`**.
4. **README** and **CONTRIBUTING** state how the **Linux** matrix and the **Windows** job differ (runner label, Python minor, and that floor / supply-chain jobs are not duplicated on Windows).
5. **Contract tests** (for example in **`tests/test_version_contract_docs.py`**) keep workflow labels, pinned minor, steps, and cache fields aligned with prose docs.
6. If **Ruff** or **pytest** cannot run on Windows for a technical reason, record the **documented** exception and the substitute checks in this section and in contributor-facing docs.
7. **`replayt-floor`** and **`supply-chain`** are **not** required on the Windows job by default.

## Python 3.13+ CI matrix (supported CPython line)

**User story:** As a **library consumer on the latest CPython**, I want **official CI signal** for **Python 3.13** so I can standardize my runtime without guessing compatibility with **replayt**, the **MCP SDK**, and this bridge.

**Context:** Expand the default workflow matrix only when **replayt** and **`mcp`** (and transitive wheels used in CI) install cleanly on **`ubuntu-latest`** runners; keep **`requires-python`** as the broad install contract and use **trove classifiers** + docs to list **CI-tested** minors.

**Acceptance criteria (refined, for implementation and review):**

1. **Matrix coverage** — [.github/workflows/ci.yml](../.github/workflows/ci.yml) **`test`** job includes **3.13** alongside **3.11** and **3.12** (or, if ecosystem wheels are still blocked, an **explicit deferral** in this section plus a **tracking issue** link—prefer adding **3.13** when unblocked).
2. **Metadata alignment** — `[project].requires-python` in **`pyproject.toml`** remains accurate for all matrix minors; **`Programming Language :: Python :: 3.x`** classifiers match **CI-tested** versions; README states **which** Python versions CI runs.
3. **Same quality bar** — On each matrix row, **`pip install -e ".[dev]"`**, then **`ruff check`**, **`ruff format --check`**, and **`pytest -q -m "not network"`** all succeed (including stdio MCP smoke modules collected by the default CI invocation).

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
