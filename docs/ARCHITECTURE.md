# Architecture: replayt-mcp-bridge

This document summarizes how the bridge is structured after the initial MCP tool surface is implemented in-process against replayt. It complements [MISSION.md](MISSION.md) (scope and trust boundaries) and [MCP_TOOLS.md](MCP_TOOLS.md) (tool catalog and schemas).

## Process and transport

- **Entry:** `python -m replayt_mcp_bridge` or the `replayt-mcp-bridge` console script → `replayt_mcp_bridge.__main__` → `server.run_stdio()`.
- **Transport:** [FastMCP](https://github.com/modelcontextprotocol/python-sdk) (`mcp.server.fastmcp`) with **`transport="stdio"`**. MCP clients speak JSON-RPC over the process stdin/stdout pair; the bridge does not open network listeners in this mode.
- **Single module of behavior:** Tool handlers and small helpers live in **`src/replayt_mcp_bridge/server.py`**. There is no separate “adapter layer” package yet; keeping one file preserves a clear boundary until the surface grows.

## Layering (conceptual)

```text
MCP host (IDE, agent runtime, CLI wrapper)
        │ JSON-RPC / MCP tool calls
        ▼
FastMCP (schema from Python signatures, stdio framing)
        │
        ▼
replayt_mcp_bridge.server  — validate/locate paths, map errors to JSON
        │
        ▼
replayt public APIs  — load_target, Workflow.contract, graph export,
                        validation_report, JSONLStore / SQLiteStore
```

**Rule:** Workflow semantics and persistence formats are **owned by replayt**. This repo owns **tool names**, **argument normalization**, **JSON-safe result shapes**, and **documented mapping** from each tool to a replayt surface.

## Tool groups

| Group | Tools | Role |
| ----- | ----- | ---- |
| Wiring / health | `replayt_echo`, `replayt_version_info` | Prove MCP wiring and report the resolved replayt version (integrator diagnostics). |
| Workflow introspection | `workflow_contract_snapshot`, `workflow_graph_mermaid` | Resolve a CLI-style **target** and expose contract and Mermaid graph text without running steps. |
| Runner (dry) | `runner_dry_run_plan` | Graph validation plus `validation_report` aligned with `replayt run --dry-check`; optional `inputs_json`, `strict_graph`, `metadata_json`, `experiment_json`, and `policy_hook_context_json` (see [MCP_TOOLS.md § Dry-check parity specification](MCP_TOOLS.md#dry-check-parity-specification-runner_dry_run_plan)). |
| Persistence read | `persistence_list_run_events` | Read-only access to events via JSONL log directory or SQLite path; default log dir matches CLI resolution when `store_hint` is omitted. |

## Shared implementation patterns

- **Structured errors:** Operational failures that should reach the client as data use `_tool_error(...)` → `{ status: "error", tool, replayt_surface, message, correlation_id }` on mapped paths (see [MCP_TOOLS.md § Mapped failure paths](MCP_TOOLS.md#mapped-failure-paths-exception--branch-inventory)). `typer.BadParameter` from `load_target` and invalid run IDs are mapped this way instead of leaking stack traces across the MCP boundary. **`correlation_id`** matches structured stderr JSON for the same invocation per [MCP_TOOLS.md § Error response shape](MCP_TOOLS.md#error-response-shape).
- **Persistence resolution:** `_resolve_persistence_paths` interprets `store_hint` (default dir, JSONL directory, or `.sqlite`/`.db` file). `_open_read_store` yields a read-only store for `load_events`.
- **Schema stability:** Tool inputs are plain Python parameters on `@mcp.tool()` functions; hosts receive JSON Schema derived by FastMCP. Prefer additive optional parameters over breaking renames.

## Observability

- **Configuration:** `configure_bridge_logging()` (from `observability.py`) runs at server startup: stderr handler, default level **`INFO`**, overridable via **`REPLAYT_MCP_BRIDGE_LOG_LEVEL`**. All bridge-owned **`os.environ`** reads live in **`observability.py`** (log level and optional **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** for `persistence_list_run_events`; see [SECURITY.md](SECURITY.md) and [Security review (phase 6)](#security-review-phase-6)).
- **Server lifecycle:** `run_stdio()` emits structured `replayt_mcp_bridge.server.start` with `transport: stdio` once before blocking on the MCP run loop.
- **Tools:** `_log_replayt_tool_boundaries` wraps every registered handler (including `replayt_echo`) and emits JSON lines for `replayt_mcp_bridge.tool.begin` / `.end` with **`tool`**, **`correlation_id`**, optional **`mcp_request_id`** from FastMCP `Context`, and result **`status`** on completion. Client argument values are never included. Extra structured fields are redacted via `redact_structure` before emission. Mapped `_tool_error` payloads use the same **`correlation_id`** (see [MCP_TOOLS.md § Error response shape](MCP_TOOLS.md#error-response-shape)).
- **Unhandled exceptions:** A structured `replayt_mcp_bridge.tool.unhandled_exception` line is logged, then `logger.exception` adds a traceback; the exception propagates and FastMCP / host behavior applies (see [MISSION.md](MISSION.md#security-and-trust-boundaries)).

## Non-goals (architecture)

- **Vendoring replayt** or reimplementing workflow execution here.
- **Implicit network or subprocess tool calls** beyond what replayt’s imported APIs already do when loading targets or stores.
- **Large generic “run arbitrary replayt CLI” tools** without explicit contracts—new tools should map to documented replayt capabilities like the mapping table in [MCP_TOOLS.md](MCP_TOOLS.md).

## CI and contributor automation

**Source of truth:** [.github/workflows/ci.yml](../.github/workflows/ci.yml) installs with `pip install -e ".[dev]"`, then runs **`ruff check`**, **`ruff format --check`**, and **`pytest -q`** as **separate steps** so the first failure is obvious. Pip cache uses `actions/setup-python` with `cache-dependency-path: pyproject.toml`. The workflow sets **`permissions: contents: read`** so the default `GITHUB_TOKEN` cannot write repository contents. The matrix covers Python **3.11** and **3.12**; the **`replayt-floor`** job reinstalls **`replayt==0.4.25`** after the editable install to guard the declared lower bound in `pyproject.toml`.

**Documentation mirror:** [README.md](../README.md) (“Local checks”) and [CONTRIBUTING.md](../CONTRIBUTING.md) list the same Ruff and pytest invocations so contributors can reproduce CI without a shared script—duplication is intentional so each doc stands alone.

**Backlog alignment:** The “pytest + ruff CI + CONTRIBUTING expectations” item is structurally satisfied: workflow on PR/push (plus `mc/**` pushes), README and CONTRIBUTING document local commands and `pip install -e ".[dev]"` for Ruff, and [MISSION.md](MISSION.md#ci-and-contributor-automation) records the refined acceptance criteria. **Default branch green** remains an operational outcome after merge.

## Review notes (risks and follow-ups)

- **Integrator documentation (architecture reviews):** [Replayt version contract surfaces](#architecture-review-replayt-version-contract) (packaging SSoT, README/CHANGELOG/CI alignment, `test_version_contract_docs.py`); [replayt 0.5.x spike (maintainer record)](#architecture-review-replayt-05x-compatibility-spike-maintainer-record) ([REPLAYT_0_5_COMPATIBILITY_SPIKE.md](REPLAYT_0_5_COMPATIBILITY_SPIKE.md), `test_replayt_0_5_spike_docs.py`); [MCP host stdio configuration](#architecture-review-mcp-host-stdio-configuration) ([MCP_HOST_CONFIG.md](MCP_HOST_CONFIG.md), README Quick start, `test_mcp_host_config_docs.py`); [stdio MCP integration smoke test](#architecture-review-stdio-mcp-integration-smoke-test) ([MISSION.md](MISSION.md#stdio-mcp-session-integration-smoke-test) spec, `test_mcp_stdio_session_smoke.py` in default CI); [runner dry-check parity parameters](#architecture-review-runner-dry-check-parity); [store_hint root allowlist](#architecture-review-store-hint-root-allowlist) (`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`, `observability.py` + `persistence_list_run_events`, `test_mcp_tools.py`); [structured tool errors and correlation IDs](#architecture-review-structured-tool-errors-and-correlation-ids) ([MCP_TOOLS.md](MCP_TOOLS.md) error spec, `correlation_id` in `server.py` + `test_mcp_tools.py`); [optional upstream doc mirror](#reference-documentation-mirror) under `docs/reference-documentation/` (offline convenience only—bridge contracts stay in first-party docs).
- **Phase 6 (security review):** `server.py`, integrator-facing **[MCP_HOST_CONFIG.md](MCP_HOST_CONFIG.md)** (trust boundary, `cwd` / discovery, `env` and secrets guidance), **[`tests/test_mcp_stdio_session_smoke.py`](../tests/test_mcp_stdio_session_smoke.py)** (fixed subprocess launch, empty tool args only, CI trust model), and the optional [`scripts/refresh_replayt_reference_docs.py`](../scripts/refresh_replayt_reference_docs.py) refresh path were reviewed against [MISSION.md](MISSION.md#security-and-trust-boundaries) and the [MCP_TOOLS.md](MCP_TOOLS.md) security table; findings are summarized in [Security review (phase 6)](#security-review-phase-6) below. For backlog **“Align runner_dry_run_plan with replayt CLI optional flags”**, optional `strict_graph` and the extra `*_json` parameters add **no new trust surfaces** beyond replayt’s existing `--dry-check` validation path (same matrix row). For backlog **“Spike compatibility with next replayt minor line (0.5.x)”**, [REPLAYT_0_5_COMPATIBILITY_SPIKE.md](REPLAYT_0_5_COMPATIBILITY_SPIKE.md) and [`test_replayt_0_5_spike_docs.py`](../tests/test_replayt_0_5_spike_docs.py) are **maintainer-only** (not on the install graph, no MCP/runtime surface); CI does not pull unpublished `0.5.x` artifacts—see [Security review (phase 6)](#security-review-phase-6) close-out. No handler or refresh-script changes were required for the stated stdio / trusted-operator model and maintainer-only PyPI refresh; CI already uses explicit read-only `contents` permissions; optional hardenings remain follow-ups.
- **Parity:** `runner_dry_run_plan` forwards `strict_graph` to `validate_workflow_graph` / `validation_report` and passes `inputs_json`, `metadata_json`, `experiment_json`, and `policy_hook_context_json` into `validation_report`, matching the CLI `--dry-check` knobs. Full CLI input merging (`resolve_run_inputs_json`) remains out of scope per [MCP_TOOLS.md](MCP_TOOLS.md#dry-check-parity-specification-runner_dry_run_plan).
- **Persistence hints:** Path/suffix heuristics work for JSONL dirs vs SQLite files; optional **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** constrains **explicit** hints only—see [Architecture review: store_hint root allowlist](#architecture-review-store-hint-root-allowlist). A structured `store_hint` (e.g. typed URI prefixes) would still be a separate, explicit contract change.
- **Event privacy:** Returned events are replayt’s stored JSON as-is; any redaction policy belongs in docs and optional bridge-level filtering if integrators require it.

### Architecture review: replayt version contract

**Scope:** Backlog **“Add compatibility matrix and CHANGELOG for replayt releases”**—confirm how **integrators** learn supported replayt versions stays coherent: one **declared** PEP 440 range in packaging, mirrored in human docs, exercised at the **lower bound** in CI, and guarded by **pytest** so edits cannot drift silently.

**Single source of truth:** `[project].dependencies` in [`pyproject.toml`](../pyproject.toml) holds the **`replayt`** constraint (today `replayt>=0.4.25,<0.5`). Install resolution and downstream metadata derive from that line—not from README prose alone.

**Integrator surfaces (intentional duplication):**

- **[README.md](../README.md)** — **Compatibility with replayt** repeats the **exact** dependency line from `pyproject.toml` and a small **bridge version × declared range × CI-tested floor** table so upgrades are plannable without opening packaging files.
- **[CHANGELOG.md](../CHANGELOG.md)** — Keep a Changelog sections; each release notes user-visible bridge changes and references the declared replayt range when it matters to consumers.
- **[CONTRIBUTING.md](../CONTRIBUTING.md) § Releases** — One paragraph tying **version bump**, **changelog**, **`pyproject.toml`**, **README** table, **`replayt-floor`** pin in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), green CI, and **git tag**.
- **[DESIGN_PRINCIPLES.md](DESIGN_PRINCIPLES.md) § replayt version contract** — Long-form policy (range vs pin, tracking upstream, Windows venv note); must quote the same range as `pyproject.toml` for discoverability.
- **[REPLAYT_0_5_COMPATIBILITY_SPIKE.md](REPLAYT_0_5_COMPATIBILITY_SPIKE.md)** — Spike log and rerun steps for the **0.5.x** minor line (PyPI check, test procedure, API touchpoints, draft changelog migration text). Update when a 0.5.x wheel/sdist exists.

**CI boundary:** Besides the default matrix (latest **replayt** compatible with the declared range), the **`replayt-floor`** job reinstalls **`replayt=={minimum}`** after `pip install -e ".[dev]"` so the **lower bound** is not only documented but **tested** against the same suite as the default job.

**Automation:** [`tests/test_version_contract_docs.py`](../tests/test_version_contract_docs.py) parses `pyproject.toml` and asserts README, CHANGELOG, CONTRIBUTING, CI, and DESIGN_PRINCIPLES stay consistent with the declared range and `[project].version`. Tests use a literal `_EXPECTED_REPLAYT_SPEC` alongside `pyproject.toml` so a partial bump fails loudly (update the constant and docs together). Floor parsing today expects a **`>=x.y.z`** patch triple; a more exotic constraint string would need a richer parser.

**Residual / extension rules:** When the minimum or range changes, update **`pyproject.toml`**, **README**, **CHANGELOG**, **CONTRIBUTING**, **DESIGN_PRINCIPLES** (if the narrative changes), **CI** `replayt-floor` reinstall and job label, and **`_EXPECTED_REPLAYT_SPEC`** in the contract tests in one maintainer pass. **Structured logging** and MCP trust-boundary architecture remain under [Observability](#observability) and [Security review (phase 6)](#security-review-phase-6).

### Architecture review: replayt 0.5.x compatibility spike (maintainer record)

**Scope:** Backlog **“Spike compatibility with next replayt minor line (0.5.x)”**—confirm the **pre-widen** workflow is documented and test-guarded **without** implying runtime support for `0.5.x` before a real PyPI artifact exists.

**Architectural boundary:** The spike markdown and its pytest module are **maintainer-only**. They are not on the install graph, do not change the declared `replayt` range by themselves, and do not add CI jobs that require an unpublished wheel. Runtime behavior still depends solely on `[project].dependencies` in [`pyproject.toml`](../pyproject.toml).

**Layering:**

- **Living record:** [REPLAYT_0_5_COMPATIBILITY_SPIKE.md](REPLAYT_0_5_COMPATIBILITY_SPIKE.md) holds the **status summary**, **rerun** recipe (editable install then `pip install --force-reinstall` to the candidate line—same pattern as **`replayt-floor`**), **bridge ↔ replayt API touchpoints** for break analysis, effort placeholders, and a **draft CHANGELOG** migration blurb for the eventual widen PR.
- **Mission alignment:** [MISSION.md](MISSION.md#replayt-minor-line-compatibility-spike-05x) states refined acceptance criteria when the range actually widens (`pyproject.toml`, README, CI floor, `_EXPECTED_REPLAYT_SPEC`, prose docs, optional reference refresh).
- **Relationship to the version contract:** The spike doc **quotes** the current `replayt` dependency line for side-by-side comparison during experiments; the **authoritative** range remains packaging plus [`tests/test_version_contract_docs.py`](../tests/test_version_contract_docs.py). Outcomes from a real `0.5.x` run should drive **one coordinated** update across those surfaces per the spike checklist.

**Automation:** [`tests/test_replayt_0_5_spike_docs.py`](../tests/test_replayt_0_5_spike_docs.py) asserts spike file presence, required section headings, the **`replayt`** line from `pyproject.toml` echoed in the spike doc, key API touchpoint strings, README / MISSION / DESIGN_PRINCIPLES / ARCHITECTURE cross-links, and MISSION mentions of **`test_version_contract_docs.py`** and **`replayt-floor`**. This is **documentation contract** coverage only—not a live test matrix against `0.5.x` while PyPI lacks a matching release.

**Phase 5 review (architecture):** Re-read [REPLAYT_0_5_COMPATIBILITY_SPIKE.md](REPLAYT_0_5_COMPATIBILITY_SPIKE.md), the MISSION spike section, DESIGN_PRINCIPLES and README pointers, and `test_replayt_0_5_spike_docs.py`: the maintainer record and tests match **blocked** upstream state; spike work introduces **no** dependency, **`replayt-floor`**, or **`_EXPECTED_REPLAYT_SPEC`** drift. Next execution step is **run the spike procedure when `0.5.x` is installable**, then widen the range per MISSION / spike checklists if results warrant it.

**Conclusion:** Architecture is **appropriate**: documented procedure plus pytest guardrails for a blocked upstream spike; integrator-facing runtime contract stays on today’s declared range until maintainers complete a deliberate widen.

### Architecture review: MCP host stdio configuration

**Scope:** Backlog **“Document copy-paste MCP host configuration for stdio”**—confirm operator-facing host JSON stays aligned with the **stdio process model**, **replayt config discovery** (`cwd`), and documented **trust boundaries**.

**Doc surface:** [MCP_HOST_CONFIG.md](MCP_HOST_CONFIG.md) holds copy-paste **Claude Desktop** (`mcpServers`) and **Cursor** (`.cursor/mcp.json`, `type: "stdio"`, `${workspaceFolder}`) examples; [README.md](../README.md) Quick start names **`replayt-mcp-bridge`** / **`python -m replayt_mcp_bridge`** and links there first. Host field names and UI evolve independently—examples defer detail to [Model Context Protocol](https://modelcontextprotocol.io/) and each host’s current docs.

**Process alignment:** Recommending **`python -m replayt_mcp_bridge`** with a **venv-resolved interpreter path** matches GUI parents that lack shell activation and matches [Process and transport](#process-and-transport) (JSON-RPC on stdin/stdout, no bridge-owned network listener).

**Working directory:** Documented **`cwd`** and Cursor workspace behavior tie replayt’s project config discovery to the **same** cwd story as the replayt CLI. Operators should point **`cwd`** at the workflow repo when the host supports it.

**Trust and security:** The host doc states the **MCP attachment** boundary up front and links [SECURITY.md](SECURITY.md) for env vars, logging, and deployment—consistent with [Security review (phase 6)](#security-review-phase-6) and [MISSION.md](MISSION.md).

**Automation:** [`tests/test_mcp_host_config_docs.py`](../tests/test_mcp_host_config_docs.py) guards presence of entrypoint strings, **SECURITY** cross-link, Claude + Cursor coverage, upstream URLs, `.cursor/mcp.json`, **`"type": "stdio"`**, **`${workspaceFolder}`**, and README Quick start linkage—parallel in spirit to [`tests/test_version_contract_docs.py`](../tests/test_version_contract_docs.py) for the declared replayt range.

**Residual / extension rules:** New **named host** blocks should follow the same pattern: minimal JSON, link upstream, extend contract tests for stable substrings, avoid unmaintainable host-version UI narrative.

**Conclusion:** Architecture is **appropriate**: one focused integrator doc, README as the front door, pytest contract tests, explicit deferral to MCP and host documentation.

### Architecture review: runner dry-check parity

**Scope:** Backlog **“Align runner_dry_run_plan with replayt CLI optional flags”**—confirm the MCP tool stays a **thin adapter** over replayt’s public validation entrypoints, optional parameters remain **additive** for existing clients, and documented **parity vs CLI** boundaries match the code path.

**Layering check:** `runner_dry_run_plan` resolves the target with `replayt.cli.targets.load_target`, then calls `replayt.cli.validation.validate_workflow_graph(wf, strict_graph=…)` and `validation_report(...)` with the same `strict_graph`, `inputs_json`, `metadata_json`, `experiment_json`, and `policy_hook_context_json` the client supplied. No shell, no subprocess, and **no reimplementation** of CLI-only resolution (`resolve_run_inputs_json` merging `--inputs-file`, repeatable `--input`, and defaults)—that gap stays explicit in [MCP_TOOLS.md § Dry-check parity](MCP_TOOLS.md#dry-check-parity-specification-runner_dry_run_plan).

**Schema / compatibility:** FastMCP derives JSON Schema from Python signatures; new knobs are optional with defaults identical to the pre-change behavior (`strict_graph=False`, other JSON parameters `None` / omitted). This matches the backlog’s “default behavior unchanged” requirement.

**Policy hook and JSON blobs:** The bridge passes client strings straight into `validation_report`; replayt validates object-shaped JSON the same way as other `*_json` slots. The CLI’s extra normalization for `--policy-hook-context-json` is **not** duplicated here—integrators supply JSON object text, as documented in MCP_TOOLS and phase 3 handoff.

**Contract tests:** `tests/test_mcp_tools.py` uses a **trusted** temporary `.py` workflow under `tmp_path` (two `@wf.step` states, no declared transitions) so `strict_graph=True` flips `status` from `ok` to `invalid` while default `strict_graph` stays `ok`; packaged `replayt_examples` targets include edges and are unsuitable for that flip. Invalid `metadata_json` is covered separately. This matches the intended replayt-boundary testing style for this repo.

**Security alignment:** Expanded inputs are validation-time only (same trust story as `replayt run --dry-check`); the phase 6 matrix row for `runner_dry_run_plan` already lists the new parameters—no dispatch change required beyond documentation cross-links.

**Phase 5 review (architecture):** Re-read [`server.py`](../src/replayt_mcp_bridge/server.py) `runner_dry_run_plan`, [MCP_TOOLS.md § Dry-check parity](MCP_TOOLS.md#dry-check-parity-specification-runner_dry_run_plan), and [`tests/test_mcp_tools.py`](../tests/test_mcp_tools.py) (`test_runner_dry_run_plan_*`): optional parameters forward to `validate_workflow_graph` / `validation_report` only; defaults match pre-change behavior; documented CLI-only `resolve_run_inputs_json` gap unchanged. Layering and security posture match this subsection’s prior checklist.

**Conclusion:** Architecture is **appropriate** for the stated scope: one handler, replayt-owned semantics, integrator-facing gaps documented. Follow-ups are **product-level** only (e.g. `@path` indirection for MCP JSON strings, or a public upstream helper for full input-resolution parity).

### Architecture review: store_hint root allowlist

**Scope:** Backlog **“Add optional store_hint root allowlist for hardened deployments”**—confirm **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** remains **opt-in**, enforcement applies **only to explicit `store_hint`** on **`persistence_list_run_events`**, env parsing stays colocated with other bridge-owned **`REPLAYT_MCP_BRIDGE_*`** reads, and rejection behavior matches structured errors plus observability contracts in **[SECURITY.md](SECURITY.md)**.

**Layering:** **`parse_store_hint_allowlist_roots()`** in [`observability.py`](../src/replayt_mcp_bridge/observability.py) returns **`None`** when unset or whitespace-only (no restriction), **`[]`** when set but no usable absolute roots parse (fail-closed for explicit hints), or a deduplicated list of resolved absolute roots. **`persistence_list_run_events`** in [`server.py`](../src/replayt_mcp_bridge/server.py) resolves paths first via **`_resolve_persistence_paths`**, then applies the allowlist **only when `store_hint is not None` and `allow_roots is not None`**. Omitted **`store_hint`** continues to use replayt’s **`resolve_log_dir(DEFAULT_LOG_DIR)`** without an allowlist check—preserving pre-feature default behavior and avoiding accidental lockout when the default log directory lies outside listed roots.

**Path semantics:** Roots and store paths use **`Path.expanduser()`** and **`Path.resolve(strict=False)`** consistent with **`_resolve_persistence_paths`**. Allowlist membership uses **`Path.is_relative_to`**. Root deduplication uses **`os.path.normcase(str(r))`** so drive-letter casing on Windows does not duplicate entries.

**Security and disclosure:** Denied or misconfigured allowlist cases return **`_tool_error`** with **generic `message` strings** that do not embed the client-supplied hint. **`emit_json_log`** records **`replayt_mcp_bridge.store_hint.rejected`** with **`reason`** **`outside_allowlist`** or **`allowlist_unusable`** and **no** store path fields—reducing hostile probe strings in shared telemetry. **Residual:** On **success**, the tool still returns **`store.path`** in the structured result (existing persistence contract); any connected MCP client may learn paths from allowed calls—that is intentional for integrators and distinct from log-safe rejection handling.

**Contract tests:** [`tests/test_mcp_tools.py`](../tests/test_mcp_tools.py) exercises allow vs deny, comma-separated roots, SQLite files under a root, unusable env parsing, omitted **`store_hint`** bypass when **`resolve_log_dir`** is monkeypatched, and asserts denied **`message`** does not contain a distinctive probe path substring. [`tests/test_security_docs.py`](../tests/test_security_docs.py) locks **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** mentions in SECURITY and observability source.

**Conclusion:** Architecture is **appropriate**: a single persistence tool owns the boundary, defaults unchanged, operator docs and the phase 6 **`store_hint` matrix row** stay aligned. No further structural split (e.g. a separate policy module) is required at current surface size.

### Architecture review: stdio MCP integration smoke test

**Scope:** Backlog **“Add an integration smoke test over the real stdio MCP session”**—define how CI exercises **real MCP JSON-RPC over stdin/stdout** (FastMCP wiring, SDK framing, tool listing and dispatch) **beyond** handler-level tests.

**Gap addressed:** [`tests/test_mcp_tools.py`](../tests/test_mcp_tools.py) invokes decorated handlers **synchronously** inside the test process—it never runs `run_stdio()` or the MCP stream loop. [`tests/test_mcp_server_stdio.py`](../tests/test_mcp_server_stdio.py) only checks that launching **`python -m replayt_mcp_bridge`** (and the console script) produces **no traceback** on startup, with **no** MCP traffic. A **session smoke test** is the narrow bridge between those two: **one** client-driven conversation proves the **end-to-end** path hosts rely on.

**Layering:** The test should treat **`replayt_mcp_bridge.server`** and **`run_stdio()`** as a **black box** behind the same **stdio** boundary as production: client in the pytest process, server subprocess (via MCP SDK `stdio_client` + `StdioServerParameters`) is acceptable and matches real deployment topology. **In-process** here means the **test orchestration and MCP client** run **inside pytest**, not that the FastMCP server must be embedded without a child process. Avoid **fixed sleeps** for readiness; use **handshake completion** and SDK context teardown so subprocess races do not dominate flakes.

**Contract surface:** Success means **initialize** (or the SDK’s session establishment) completes, **`replayt_version_info`** or **`replayt_echo`** appears in **`tools/list`**, and **`tools/call`** returns a JSON-shaped result matching [MCP_TOOLS.md](MCP_TOOLS.md). Failure modes worth catching early: **stdio deadlock**, **broken registration** (tool absent from list), **import/wiring errors** after a dependency upgrade, and **hung server** (address with explicit timeouts).

**Automation:** [`tests/test_mcp_stdio_session_smoke.py`](../tests/test_mcp_stdio_session_smoke.py) runs in the **existing** CI pytest step (MCP SDK `stdio_client` + `ClientSession`, `StdioServerParameters` with `sys.executable` and `-m replayt_mcp_bridge`, `cwd` at repo root, `asyncio.wait_for` wall timeout). It stays isolated from handler contracts and subprocess-only startup checks—no separate workflow job unless runtime grows enough to warrant optional splitting.

**Residual:** If a future maintainer introduces an **official in-memory** transport for FastMCP tests, the **stdio** smoke test should **remain** as the canonical check for the operator entrypath; secondary tests may duplicate coverage for speed only if they do not replace stdio.

**Phase 5 review (architecture):** Re-read [`tests/test_mcp_stdio_session_smoke.py`](../tests/test_mcp_stdio_session_smoke.py) against [MISSION.md](MISSION.md#stdio-mcp-session-integration-smoke-test) acceptance criteria: **default CI**—module is collected with the rest of `tests/` in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml); **bounded runtime**—`asyncio.wait_for(..., 45.0)` wraps the session with a clear `AssertionError` on timeout; **successful tool path**—`initialize`, `list_tools` (asserts `replayt_version_info` present), `call_tool("replayt_version_info", {})`, structured `status: "ok"` and non-empty `replayt_version` (via `structuredContent` or JSON in `TextContent`); **clear failures**—missing registration and `isError` results assert with context; **determinism**—no fixed sleeps, protocol completion drives readiness. Unchanged follow-ups: MCP `stdio_client` default env may diverge from the pytest parent if CI ever relied on extra variables (current editable install is fine); optional **`pytest-timeout`** remains a maintainer choice alongside `wait_for`.

**Conclusion:** Architecture expectation is **appropriate**: one focused pytest module, MCP SDK client, operator-aligned launch args, handshake-driven synchronization, bounded timeouts. Implementation is **in place**; [MISSION.md](MISSION.md#stdio-mcp-session-integration-smoke-test) holds the refined acceptance criteria.

### Reference documentation mirror

**Scope:** Optional **attributed** copies of replayt’s **sdist**-shipped `README.md` and `LICENSE` under [`docs/reference-documentation/`](reference-documentation/README.md), refreshed via [`scripts/refresh_replayt_reference_docs.py`](../scripts/refresh_replayt_reference_docs.py). This supports **offline reading** for humans and agents; it is **not** part of the MCP runtime or install graph.

**Architectural boundary:** [MISSION.md](MISSION.md) and [MCP_TOOLS.md](MCP_TOOLS.md) remain the **only** mission-critical integration contracts. The mirror README states explicitly that snapshots must not override bridge docs. Relative links inside vendored replayt README may target paths absent from the partial mirror (full tree requires upstream or a wider refresh policy).

**Alignment with packaging:** The default refresh version is parsed from the **`replayt>=…`** lower bound in `pyproject.toml`; [`tests/test_reference_documentation.py`](../tests/test_reference_documentation.py) locks snapshot directory naming, attribution content, and helper behavior **without PyPI** (synthetic tar fixtures + `importlib` load of the script). Drift rules: when the declared floor changes, run the refresh script, update [`docs/reference-documentation/README.md`](reference-documentation/README.md) layout table if the path changes, and extend tests if layout rules change.

**Operational / trust:** `pypi_sdist_url` and `main()` perform **HTTPS fetches to PyPI** only; contributors run refresh manually. CI does not depend on network for this feature. No secrets or subprocess shells are involved in the refresh helpers beyond stdlib `urllib` and `tarfile`.

### Security review (phase 6)

**Scope:** Phase **6** security pass on **`server.py`** (tool surface and dispatch) against [MISSION.md](MISSION.md#security-and-trust-boundaries) and [MCP_TOOLS.md § Security](MCP_TOOLS.md#security), plus **`observability.py`** for structured logging and key-based redaction (aligned with [docs/SECURITY.md](SECURITY.md)). The same pass covers **[MCP_HOST_CONFIG.md](MCP_HOST_CONFIG.md)** for backlog **“Document copy-paste MCP host configuration for stdio”**—documentation only, but security-relevant because host JSON governs **who spawns the bridge**, **`cwd`**, and inherited **`env`**.

**MCP host configuration doc:** Examples use **`command` / `args`** (and optional **`cwd`**, **`env`**) in the shapes hosts document—no shell string concatenation and no bridge-owned network endpoints introduced by the file. The opening **trust boundary** paragraph and link to **[SECURITY.md](SECURITY.md)** match the mission’s MCP hosting story. The **Optional environment** section names **`REPLAYT_MCP_BRIDGE_LOG_LEVEL`** as the illustrative `env` key and tells operators not to commit secrets, consistent with SECURITY’s logging and credential tables. **`cwd`** and Cursor **`${workspaceFolder}`** guidance align child-process working directory with replayt config discovery (same “workflow tree on disk” exposure model as the CLI when the path is correct). Residual: real configs may contain **identifying paths** or team-specific layout—treat shared snippets and support bundles like other operator config. **[`tests/test_mcp_host_config_docs.py`](../tests/test_mcp_host_config_docs.py)** and **[`tests/test_security_docs.py`](../tests/test_security_docs.py)** lock cross-links and required strings; they are not a substitute for per-host threat models when parents add debug logging or remote attachment.

**Observability (`observability.py`):** `emit_json_log` runs caller fields through **`redact_structure`** (case-insensitive key substrings: password, secret, token, api_key, etc.) before `json.dumps`; values under non-matching keys are unchanged—same residual as noted under [Observability](#observability) above. **`observability.py`** is the only bridge module that reads **`os.environ`**: **`REPLAYT_MCP_BRIDGE_LOG_LEVEL`** (verbosity only; invalid names fall back to **INFO**) and **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** (optional allowlist parsed for `persistence_list_run_events`; see [SECURITY.md](SECURITY.md)). `configure_bridge_logging` attaches one stderr `StreamHandler` with `%(message)s`, **`propagate=False`** on `replayt_mcp_bridge` to avoid duplicate root handlers, and does not log environment values. `json.dumps(..., default=str)` is a last resort for non-JSON-native field values; current bridge emissions use JSON-safe primitives.

**Structured errors and `correlation_id` (backlog: bounded failures):** Phase **6** security pass for **Return structured tool errors with correlation IDs for bounded failures** confirms `_tool_error` is used only on paths listed in [MCP_TOOLS.md § Mapped failure paths](MCP_TOOLS.md#mapped-failure-paths-exception--branch-inventory). The only broad handler is inside `_log_replayt_tool_boundaries` (`except Exception`), which emits `replayt_mcp_bridge.tool.unhandled_exception` with the same **`correlation_id`** as **`tool.begin`** then **re-raises**—so unmapped failures are not silently swallowed as `{ status: error }` tool data. **`correlation_id`** is a per-invocation correlation handle (FastMCP `request_id` when non-empty, else UUID4) for operator matching in stderr JSON; it is not a credential and does not change the MCP attachment trust model. [`tests/test_mcp_tools.py`](../tests/test_mcp_tools.py) covers mapped result vs log alignment and unmapped propagation with shared ids on lifecycle lines.

**Phase 6 close-out:** For backlog **Add optional store_hint root allowlist for hardened deployments**, verified `parse_store_hint_allowlist_roots`, `_path_allowed_under_store_hint_roots` / `Path.is_relative_to`, and `persistence_list_run_events` match **[Architecture review: store_hint root allowlist](#architecture-review-store-hint-root-allowlist)** and SECURITY.md (explicit-hint-only enforcement, generic `_tool_error` messages, `replayt_mcp_bridge.store_hint.rejected` without store paths). Re-checked all other `@mcp.tool()` handlers, `_resolve_persistence_paths` / `_open_read_store`, and the rest of `observability.py` against MISSION, MCP_TOOLS § Security, and SECURITY.md. `runner_dry_run_plan` still resolves `target` via `load_target` then forwards client strings and `strict_graph` only to `validate_workflow_graph` / `validation_report` (in-process; no shell or subprocess). **Workflow phase 6 (security) for backlog [Align runner_dry_run_plan with replayt CLI optional flags](#architecture-review-runner-dry-check-parity):** after the phase 5 architecture-doc refresh, re-read `server.py` `runner_dry_run_plan` and the tool matrix below—optional `inputs_json` / `metadata_json` / `experiment_json` / `policy_hook_context_json` / `strict_graph` add **no dispatch surfaces** beyond replayt’s dry-check validation APIs already summarized in the **`runner_dry_run_plan`** row; **no code changes** and **no security-table edits** were required beyond this explicit close-out note. Dispatch elsewhere remains replayt/`pathlib` only; `_log_replayt_tool_boundaries` still omits tool arguments from log payloads and emits **`correlation_id`** on `replayt_mcp_bridge.tool.begin` / `.end` / `.unhandled_exception` (aligned with mapped `_tool_error` payloads and [MCP_TOOLS.md § Error response shape](MCP_TOOLS.md#error-response-shape)); contract tests (`test_security_docs.py`, `test_observability.py`, `test_mcp_tools.py`) enforce the **observability-only** `os.environ` read surface and redaction. **MCP_HOST_CONFIG.md** review and the **SECURITY.md** → **MCP_HOST_CONFIG.md** deployment cross-link are documented above. For backlog **“Add an integration smoke test over the real stdio MCP session”**, reviewed [`tests/test_mcp_stdio_session_smoke.py`](../tests/test_mcp_stdio_session_smoke.py): subprocess argv and `cwd` are fixed (no client-controlled launch), and the only tool call uses an empty argument object—see **CI stdio session smoke** below. **Workflow phase 6 (security) for backlog [Spike compatibility with next replayt minor line (0.5.x)](#architecture-review-replayt-05x-compatibility-spike-maintainer-record):** [REPLAYT_0_5_COMPATIBILITY_SPIKE.md](REPLAYT_0_5_COMPATIBILITY_SPIKE.md) and [`tests/test_replayt_0_5_spike_docs.py`](../tests/test_replayt_0_5_spike_docs.py) add **no** MCP tools, bridge imports, subprocess/shell paths, **`os.environ`** reads, or network listeners; they are **documentation and pytest contract** coverage only. Default CI continues to install replayt within the **declared** `pyproject.toml` range and does **not** execute `pip install --force-reinstall` to an unpublished `0.5.x`. Maintainer spike rerun steps use the same **pip / PyPI** trust model as ordinary development; a future widen PR changes **declared** third-party dependencies—review wheels/sdists and organizational supply-chain policy before merge like any dependency bump. The table below remains the authoritative residual-risk summary for tool inputs.

**Reference doc refresh script (contributor-only, non-runtime):** [`scripts/refresh_replayt_reference_docs.py`](../scripts/refresh_replayt_reference_docs.py) is **not** on the installed package surface: `[project.scripts]` exposes only `replayt-mcp-bridge`, and setuptools discovers packages under `src/` only—maintainers run the script explicitly from a checkout. **`main()`** uses stdlib **`urllib`** to **`https://pypi.org/...`** and to the **sdist URL returned by PyPI’s JSON API** (same supply-chain trust model as `pip download`). **`extract_readme_license`** reads **two regular-file members** via **`TarFile.extractfile`** and writes **`README.md`** and **`LICENSE`** under a versioned directory beneath `docs/reference-documentation/snapshots/`—no **`extractall`**, no pathnames taken from the archive for destination paths, so **tar path traversal / slip** into arbitrary write locations is not in play for this code path. **`--version`** only affects the PyPI URL segment; it does not introduce subprocesses or a shell. Residual: a **compromised PyPI response or sdist** (or **MITM** if TLS is broken) could deliver malicious content into **`docs/`**—treat refreshed snapshots like **any other third-party artifact** (review diffs, use trusted networks). CI does **not** invoke this script, so CI stays **offline-safe** for the mirror tests.

**Transport and process:** The documented entrypath remains **stdio-only**; the bridge does not open its own network listeners. Whoever controls the parent process (or can substitute stdio) can invoke tools—treat MCP attachment as a **trusted-operator** boundary, not anonymous wide-area exposure.

**CI stdio session smoke (`tests/test_mcp_stdio_session_smoke.py`):** Default CI runs an MCP SDK client that spawns the bridge with **fixed** `StdioServerParameters`: `command=sys.executable`, `args=["-m", "replayt_mcp_bridge"]`, and `cwd` at the repository root. **No** test-supplied or MCP-host strings enter the child **argv**; protocol traffic is **`initialize`**, **`tools/list`**, and **`call_tool("replayt_version_info", {})`** with an empty dict. The module therefore **does not widen** the production MCP tool trust model—it validates wiring only. **Residual:** Trust in the checkout (same as any pytest that imports the package); the MCP client’s default subprocess **environment** may differ from the pytest parent (see [Architecture review: stdio MCP integration smoke test](#architecture-review-stdio-mcp-integration-smoke-test)).

**Dispatch path:** Tool handlers call replayt APIs and `pathlib` helpers only. There is **no** `subprocess`, `os.system`, or shell string assembly for MCP arguments.

| Input / surface | Bridge handling | Residual risk |
| --------------- | --------------- | ------------- |
| `target` | Passed to `load_target` | Same as the replayt CLI: **Python import** and **workflow file reads** for resources the server user can access. |
| `inputs_json`, `metadata_json`, `experiment_json`, `policy_hook_context_json`, and `strict_graph` on `runner_dry_run_plan` | Passed to `validate_workflow_graph` / `validation_report` after target load (same as `replayt run --dry-check`) | Malformed or non-object JSON is reported as `status: "invalid"` via replayt’s validation report (not a bridge-level exception in spot checks). Other unexpected replayt exceptions remain possible and follow the unhandled path below. |
| `store_hint` | `expanduser`, `Path.resolve(strict=False)`, then read-only `JSONLStore` / `SQLiteStore`; optional **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** roots check for **explicit** hints only | Any path the OS allows the process to open unless an allowlist is configured; **symlinks** resolve per platform rules. Plain files that are not SQLite are rejected with `_tool_error`. Denied hints return `_tool_error` without echoing the probe path; see SECURITY.md. |
| `run_id` | `validate_run_id_for_store` before `load_events` | Identifier validation only; **event payloads** are returned as stored (no bridge redaction). |
| `replayt_echo(message)` | Returned in the structured result | **Reflection** if echoed content is fed into models or UIs; bridge-only tool, still wrapped by `_log_replayt_tool_boundaries` for consistent lifecycle logs (arguments are not logged). |

**Information disclosure:** `_tool_error` returns string `message` fields (from `typer.BadParameter`, `ValueError`, `OSError`, or hint validation). Those strings may include paths or operational detail useful to integrators and visible to **any** connected MCP client—scope who may attach. **Unhandled** exceptions emit a structured `replayt_mcp_bridge.tool.unhandled_exception` line, then `logger.exception` and propagation; presentation to clients depends on FastMCP / host behavior (see [MISSION.md](MISSION.md#security-and-trust-boundaries)).

**Logging:** Tool handlers emit JSON lines with **tool** name, **correlation_id**, optional **mcp_request_id**, and result **status** at begin/end—**no** client argument values. Sensitive-shaped extra fields are redacted in `observability.py`.

**Follow-ups (product / optional hardening):** A separate narrow catch for *additional* unexpected exception classes (beyond today’s mapped set) would still require an explicit inventory update and tests. Optional event field redaction; stricter documentation staging if integrators want a “milestone 1 only” tool exposure story.

### Architecture review: structured tool errors and correlation IDs

**Scope:** Backlog **“Return structured tool errors with correlation IDs for bounded failures”**—nail down which failures become `{ "status": "error", … }`, how **`correlation_id`** ties MCP tool results to stderr JSON for the same invocation, and what stays **unmapped** (still logged + propagated).

**Single source of truth:** [MCP_TOOLS.md § Error response shape](MCP_TOOLS.md#error-response-shape) (payload fields, **`correlation_id`** policy, mapped inventory table, unmapped exception rule). [SECURITY.md § MCP host and client logs](SECURITY.md#mcp-host-and-client-logs) explains operator-facing log matching.

**Code alignment:** `server.py` uses `_tool_error` only on the listed mapped paths; `_log_replayt_tool_boundaries` assigns one **`correlation_id`** per invocation (FastMCP `request_id` when non-empty, else UUID4), emits it on begin/end/unhandled logs, and `_tool_error` attaches the same value. `replayt_mcp_bridge.store_hint.rejected` lines include **`correlation_id`** when emitted inside a tool handler.

**Residual / extension rules:** Any new mapped exception or branch must update the MCP_TOOLS inventory table, add or extend pytest coverage, and extend CHANGELOG when behavior is user-visible. Broad `except Exception` handlers that return structured errors are **out of scope** unless each new category is named and tested.

**Conclusion:** Bounded structured errors carry **`correlation_id`** in tool results and stderr JSON; pytest covers a mapped path and unmapped propagation with correlated logs.

## Related files

| Path | Purpose |
| ---- | ------- |
| `README.md` | Compatibility table and declared replayt line (mirrors `pyproject.toml`) |
| `CHANGELOG.md` | Keep a Changelog history; release notes for integrators |
| `pyproject.toml` | Bridge version and declared `replayt` dependency range (SSoT) |
| `.github/workflows/ci.yml` | Ruff + pytest workflow and replayt floor job |
| `CONTRIBUTING.md` | Local check commands aligned with CI; Releases paragraph |
| `tests/test_version_contract_docs.py` | Contract tests: docs + CI aligned with `pyproject.toml` |
| `docs/REPLAYT_0_5_COMPATIBILITY_SPIKE.md` | Maintainer spike log and rerun steps for replayt `0.5.x` before widening `<0.5` |
| `tests/test_replayt_0_5_spike_docs.py` | Contract tests: spike doc sections, touchpoints, links, pyproject echo |
| `docs/SECURITY.md` | Env vars, logging/redaction, deployment, MCP host trust (operator-facing) |
| `src/replayt_mcp_bridge/server.py` | FastMCP app, tool implementations, persistence helpers |
| `src/replayt_mcp_bridge/observability.py` | Structured JSON logging, redaction, log level env |
| `src/replayt_mcp_bridge/__main__.py` | Stdio server entry |
| `docs/MCP_TOOLS.md` | Tool → replayt mapping and input shapes |
| `docs/MCP_HOST_CONFIG.md` | MCP host JSON / stdio launch examples (Claude Desktop, Cursor) |
| `tests/test_mcp_tools.py` | Contract tests at the replayt boundary |
| `tests/test_mcp_stdio_session_smoke.py` | MCP stdio session smoke: handshake + `replayt_version_info` via real JSON-RPC—see [Architecture review: stdio MCP integration smoke test](#architecture-review-stdio-mcp-integration-smoke-test) |
| `tests/test_mcp_server_stdio.py` | Subprocess startup without traceback (no MCP messages) |
| `tests/test_mcp_host_config_docs.py` | Contract tests for MCP host config doc and README linkage |
| `tests/test_security_docs.py` | Doc and policy contract tests (SECURITY.md, README, env read policy) |
| `tests/test_observability.py` | Redaction and structured log emission tests |
| `docs/reference-documentation/README.md` | Optional mirror scope, attribution policy, refresh instructions |
| `scripts/refresh_replayt_reference_docs.py` | PyPI sdist download and snapshot refresh (network in `main()` only) |
| `tests/test_reference_documentation.py` | Contract tests for mirror layout and offline-safe refresh helpers |
