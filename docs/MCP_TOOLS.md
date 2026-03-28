# MCP tools (initial surface)

This bridge exposes a small, versioned set of MCP tools that map to **replayt** APIs or CLI workflows. **Input schemas stay stable** so clients can integrate early; workflow, dry-check, and persistence tools call replayt in-process, while **`replayt_doctor`** invokes **`python -m replayt doctor`** in a subprocess with a fixed argv list (**no** shell)—see [Backlog spec: `replayt_doctor`](#backlog-spec-replayt_doctor-mcp-wrapper-for-replayt-doctor). Handlers live in `src/replayt_mcp_bridge/tools_*.py`, registered when `server.py` imports those modules; **`replayt_echo`** is hidden from **`tools/list`** when the optional **[diagnostic echo gate](#backlog-spec-optional-omission-of-diagnostic-echo-tools-from-registration)** is on. For process boundaries and how tools sit above replayt, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Execution timeouts

**Problem:** Most handlers call replayt **in-process**; **`replayt_doctor`** awaits a bounded subprocess. Without a bridge-level wall-clock policy, a single stuck call can block the whole MCP stdio session.

**Approach:** Apply an **outer** `asyncio.wait_for` (or equivalent) around the async body of each **in-scope** tool (see [Tools in scope](#execution-timeouts-tools-in-scope)). This is **in addition to** any timeouts inside replayt (HTTP clients, hooks, etc.); upstream behavior is not reimplemented here.

### Configuration and precedence

- **Units:** Non-negative **floating-point seconds** (fractional values allowed, e.g. `0.1`).
- **Parsing:** Non-numeric values, empty strings, or values **`≤ 0`** at a given step are treated as described below. Implementations **SHOULD** log a warning when a value is invalid and ignored.
- **Read site:** All `REPLAYT_MCP_BRIDGE_*` timeout variables are read only in `observability.py`, consistent with other bridge env knobs ([SECURITY.md](SECURITY.md)).

**Precedence (highest wins):**

1. **`REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_<TOOL>_SECONDS`** — Per-tool override. **`<TOOL>`** is the MCP tool name in **ASCII uppercase with underscores**, matching the registered name exactly (e.g. `REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_WORKFLOW_CONTRACT_SNAPSHOT_SECONDS`, `…_RUNNER_DRY_RUN_PLAN_SECONDS`, `…_PERSISTENCE_LIST_RUN_EVENTS_SECONDS`, `…_REPLAYT_DOCTOR_SECONDS`). When set and **strictly > 0** after parsing, this is the wall-clock budget for that tool.
2. **`REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_SECONDS`** — Global default for in-scope tools when (1) is unset or invalid.
3. **Built-in default** — When (1) and (2) are both unset or invalid, the bridge **MUST** apply a built-in limit of **`300`** seconds for in-scope tools (conservative default for shared stdio sessions).

**Disabling bridge timeouts:** If the **winning** value (after precedence) is **`≤ 0`**, that tool invocation runs **without** bridge `wait_for` (unlimited wall clock from the bridge’s perspective). To disable globally while keeping per-tool limits, set the global variable to `0` and set positive per-tool overrides where needed.

### Tools in scope

| MCP tool | Bridge timeout |
| -------- | -------------- |
| `workflow_contract_snapshot` | **Required** |
| `workflow_graph_mermaid` | **Required** |
| `runner_dry_run_plan` | **Required** |
| `persistence_list_run_events` | **Required** |
| `replayt_doctor` | **Required** |
| `replayt_echo` | **Exempt** (synchronous, trivial) |
| `replayt_version_info` | **Exempt** (package metadata only) |

### Structured error on timeout

When the bridge deadline elapses first, the tool result **MUST** include:

- `status: "error"`
- `tool` — MCP tool name
- `replayt_surface: "bridge_timeout"`
- `message` — Stable English operator text (current text: **`Tool execution timed out`**)
- `correlation_id` — Same contract as [Error response shape](#error-response-shape); **MUST** align with the invocation’s structured stderr lines when boundary logging wraps the handler.

**Optional additive keys (SHOULD):** `timeout_seconds` (effective limit) and `timeout_source` (`"per_tool_env"`, `"global_env"`, or `"default"`). Clients **MUST** ignore unknown keys.

**MUST NOT:** Include a Python traceback in the returned dict for this mapped path.

**Stderr:** Emit a structured error log line with `event: "replayt_mcp_bridge.tool.timeout"` including `tool`, `correlation_id`, and the effective timeout.

### Pytest / CI bar (implementation phase)

1. **Wrapper regression** — Keep (or add) coverage that the timeout helper returns the structured shape when a dummy async callable exceeds a short limit.
2. **Replayt-touching path** — At least one test that calls a **registered** in-scope tool with a **short** positive timeout, using a **monkeypatched delay** on a replayt (or bridge) function on the real code path (not only an isolated dummy), and asserts: `status == "error"`, `replayt_surface == "bridge_timeout"`, `correlation_id` present, and no traceback payload in the result dict.

### Backlog closure checklist

For **Define and enforce per-tool execution timeouts for replayt-backed handlers**:

- [ ] Precedence, units, built-in **300** s default, and disable semantics match this section and [SECURITY.md](SECURITY.md).
- [ ] Every **Required** tool in [Tools in scope](#tools-in-scope) is wrapped in code.
- [ ] Pytest meets [Pytest / CI bar](#pytest--ci-bar-implementation-phase) above.

## Mapping: tool → replayt capability

| MCP tool | Replayt / CLI surface | Notes |
| -------- | ---------------------- | ----- |
| `replayt_echo` | _(bridge only)_ | Proves MCP wiring; echoes input. Omitted from **`tools/list`** when **`REPLAYT_MCP_BRIDGE_DISABLE_DIAGNOSTIC_ECHO_TOOLS`** is truthy or **`--no-diagnostic-echo-tools`** is used—see [Backlog spec: optional omission of diagnostic echo tools from registration](#backlog-spec-optional-omission-of-diagnostic-echo-tools-from-registration). |
| `replayt_version_info` | `replayt.__version__` / `replayt.__version_tuple__` | Reads installed replayt via the same helpers as `replayt_mcp_bridge.installed_replayt_version`. |
| `workflow_contract_snapshot` | `Workflow.contract()`, via `replayt.cli.targets.load_target` | Same **target** grammar as `replayt contract` / `replayt run` (e.g. `module.path:wf`, `workflow.py`). Returns `{ status, target, contract }` or `{ status: error, tool, replayt_surface, message }`. Subject to [Execution timeouts](#execution-timeouts). |
| `workflow_graph_mermaid` | `replayt.graph_export.workflow_to_mermaid` | Aligns with `replayt graph` Mermaid output. Returns `{ status, target, mermaid }` or an error object. Subject to [Execution timeouts](#execution-timeouts). |
| `runner_dry_run_plan` | `replayt run --dry-check` (graph validation + `validation_report`) | Validates graph and optional JSON strings without executing steps or writing logs. Returns `{ status: ok \| invalid, report }` matching `replayt.validate_report.v1`, or an error object. Optional `strict_graph` and `metadata_json` / `experiment_json` / `policy_hook_context_json` match the CLI `--dry-check` knobs; defaults and gaps are documented under [Dry-check parity specification (runner_dry_run_plan)](#dry-check-parity-specification-runner_dry_run_plan). Subject to [Execution timeouts](#execution-timeouts). **Hook / env:** in-process dry-check may reach replayt paths that use **`policy_hook_context_json`** and upstream policy-hook behavior; see [Hook env inheritance and MCP deployments](#hook-env-inheritance-and-mcp-deployments-backlog-spec), [SECURITY.md § Minimal environment inheritance](SECURITY.md#minimal-environment-inheritance), [SECURITY.md § Variables that commonly affect this bridge](SECURITY.md#variables-that-commonly-affect-this-bridge), and [ARCHITECTURE.md § Architecture review: runner dry-check parity](ARCHITECTURE.md#architecture-review-runner-dry-check-parity). |
| `persistence_list_run_events` | `EventStore.load_events` on JSONL log dir or SQLite DB | `store_hint`: omit for project-resolved default log dir (`resolve_log_dir(DEFAULT_LOG_DIR)`), or pass a legacy filesystem path (JSONL **directory** or `.sqlite` / `.db` file per suffix heuristics), or an explicit typed hint (`file:…`, `jsonl-dir:…`, `jsonl:…`, `sqlite:…`—see [store_hint grammar](#store_hint-grammar)). Optional env **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** (see [SECURITY.md](SECURITY.md)) restricts **explicit** `store_hint` paths to resolved locations under listed absolute roots. Optional **`event_fields`** (list of strings): when non-empty, each **object-shaped** event keeps **only those top-level keys** that exist on the event; omit, `null`, or **`[]`** means no MCP-level allowlist for that call (see [Field allowlist semantics](#field-allowlist-semantics)). Optional env **`REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`** supplies a **default** comma-separated allowlist when **`event_fields`** is omitted or `null`; explicit **`event_fields: []`** overrides that default to “no allowlist.” Optional env **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`** (truthy: **`1`**, **`true`**, **`yes`**, **`on`**) applies **`redact_structure`** **after** any top-level field selection. Default for existing callers remains full pass-through when those knobs are unset. **Volume limits** (max event count + compact JSON UTF-8 size on the post-`load_events` list, with env defaults and optional **`max_events`** / **`max_total_bytes`** per call) are enforced per [Run event volume limits](#run-event-volume-limits-backlog-spec) (`bridge_run_events_volume` on over-limit). Returns `{ status, run_id, event_count, events, store }` or an error object. Subject to [Execution timeouts](#execution-timeouts). |
| `replayt_doctor` | `python -m replayt doctor` (**subprocess**, JSON via **`--format json`**) | Default **`skip_connectivity: true`** passes **`--skip-connectivity`**. Optional **`target`** is validated with **`replayt.cli.targets.load_target`** before the subprocess (same grammar as workflow tools). Optional **`strict_graph`**, **`inputs_json`**, **`inputs_file`**, **`input_overrides`** map to CLI flags per [Backlog spec: `replayt_doctor`](#backlog-spec-replayt_doctor-mcp-wrapper-for-replayt-doctor). Returns `{ status: ok, tool, doctor, replayt_exit_code }` on success (including **`healthy: false`** inside **`doctor`**); structured errors for bad **`target`**, parse failures, **`OSError`** starting the child, or **`bridge_timeout`**. Subject to [Execution timeouts](#execution-timeouts). **Hook / env:** subprocess inherits the bridge process environment; replayt inside the child may read hook argv and run hook commands per upstream—see [Hook env inheritance and MCP deployments](#hook-env-inheritance-and-mcp-deployments-backlog-spec), [SECURITY.md § Minimal environment inheritance](SECURITY.md#minimal-environment-inheritance), [SECURITY.md § Variables that commonly affect this bridge](SECURITY.md#variables-that-commonly-affect-this-bridge), and [ARCHITECTURE.md § Security review (phase 6)](ARCHITECTURE.md#security-review-phase-6) (`replayt_doctor` matrix row). |

### Hook env inheritance and MCP deployments (backlog spec)

The bridge **does not** sandbox replayt. Handlers and any replayt **subprocess** the bridge starts run as the **same OS user** as the MCP server, with the **same inherited environment** (modulo how the operator launched the process). Hook commands, policy-hook subprocesses, and upstream code paths see whatever **`REPLAYT_*_HOOK`**, **`REPLAYT_*_HOOK_TIMEOUT`**, **`REPLAYT_POLICY_HOOK_*`**, and related vars the process environment contains. To reduce exposure, use the patterns in [SECURITY.md § Minimal environment inheritance](SECURITY.md#minimal-environment-inheritance) and the name list in [SECURITY.md § Variables that commonly affect this bridge](SECURITY.md#variables-that-commonly-affect-this-bridge).

**Classification (this bridge’s wiring):**

| Category | MCP tools | Hook / subprocess surface |
| -------- | --------- | ------------------------- |
| **Subprocess** | `replayt_doctor` | Runs **`python -m replayt doctor`** in a child process; the child inherits the server env by default. Upstream may read hook argv and run hooks according to what **`doctor`** exercises. Matrix row: [ARCHITECTURE.md § Security review (phase 6)](ARCHITECTURE.md#security-review-phase-6). |
| **In-process, hook-adjacent** | `runner_dry_run_plan` | Calls replayt in-process; optional **`policy_hook_context_json`** (and related dry-check args) are forwarded into **`validation_report`**. Upstream may perform policy-hook-related work when those features are used. See [ARCHITECTURE.md § Architecture review: runner dry-check parity](ARCHITECTURE.md#architecture-review-runner-dry-check-parity) (**Policy hook and JSON blobs**). |
| **In-process, no extra replayt subprocess** | `workflow_contract_snapshot`, `workflow_graph_mermaid`, `persistence_list_run_events`, `replayt_version_info`, `replayt_echo` | This package does not spawn a second OS subprocess for replayt on these paths. They still run with **full env inheritance** in the server process, and replayt may **read** hook-related environment variables during normal library use. A “read-only” tool name does **not** mean hook vars are unused. |

**Original backlog title:** **Document and test replayt hook env inheritance in MCP deployments**. Acceptance criteria and traceability: [MISSION.md § Replayt hook env inheritance in MCP deployments (backlog spec)](MISSION.md#replayt-hook-env-inheritance-in-mcp-deployments-backlog-spec). **Implementation status:** **Shipped** (workflow phase **3** Builder); contract coverage in [`tests/test_security_docs.py`](../tests/test_security_docs.py).

## Input shapes (JSON Schema concepts)

Tools are registered with the official Python MCP SDK (`mcp.server.fastmcp`); hosts receive JSON Schema derived from the Python signatures below.

### String parameter bounds (backlog spec)

**Backlog title:** **Add JSON-schema bounds on high-risk string tool parameters** — traceability and close-out checklist: [MISSION.md § JSON-schema bounds on high-risk string tool parameters (backlog spec)](MISSION.md#json-schema-bounds-on-high-risk-string-tool-parameters-backlog-spec). **Implementation status:** **Shipped** (workflow phase **3** Builder); numeric limits below match [`tools_bounds.py`](../src/replayt_mcp_bridge/tools_bounds.py) and FastMCP-derived **`tools/list`** schemas.

**Goal:** Declare **`maxLength`**, **`maxItems`**, and per-element string caps so MCP hosts can pre-validate and the bridge rejects absurd inputs **before** `load_target`, persistence resolution, or large `json.loads` work.

**Tier A — path-like and target-resolution strings** (generous for deep filesystem paths, Windows prefixes, and `module.path:variable` targets):

| Parameter | Tool(s) | `maxLength` (Unicode code points) | Notes |
| --------- | ------- | ----------------------------------- | ----- |
| `target` | `workflow_contract_snapshot`, `workflow_graph_mermaid`, `runner_dry_run_plan` | **8192** | Above typical `PATH_MAX`-class limits; still bounded. |
| `target` | `replayt_doctor` (optional) | **8192** | Same grammar as workflow tools when present. |
| `store_hint` | `persistence_list_run_events` (optional) | **8192** | Includes typed prefixes (`file:`, `jsonl-dir:`, …) plus path text. |
| `inputs_file` | `replayt_doctor` (optional) | **8192** | Filesystem path passed to subprocess argv. |

**Tier B — identifiers:**

| Parameter | Tool(s) | `maxLength` | Notes |
| --------- | ------- | ----------- | ----- |
| `run_id` | `persistence_list_run_events` | **1024** | Headroom beyond typical run id formats; replayt may still reject invalid ids first. |

**Tier C — large JSON object text** (dry-check / doctor inputs; cap total paste size per field):

| Parameter | Tool(s) | `maxLength` | Notes |
| --------- | ------- | ----------- | ----- |
| `inputs_json` | `runner_dry_run_plan`, `replayt_doctor` | **1_048_576** (1 MiB) | JSON **text**; malformed JSON remains replayt’s `invalid` / error story **after** length passes. |
| `metadata_json` | `runner_dry_run_plan` | **1_048_576** | Same as above. |
| `experiment_json` | `runner_dry_run_plan` | **1_048_576** | Same as above. |
| `policy_hook_context_json` | `runner_dry_run_plan` | **1_048_576** | Same as above. |

**Tier D — diagnostic echo:**

| Parameter | Tool | `maxLength` | Notes |
| --------- | ---- | ----------- | ----- |
| `message` | `replayt_echo` | **262_144** (256 KiB) | Large enough for integration tests; still caps accidental dumps. |

**Tier E — string lists:**

| Parameter | Tool | `maxItems` | Per-element `maxLength` | Notes |
| --------- | ---- | ---------- | ------------------------ | ----- |
| `input_overrides` | `replayt_doctor` | **128** | **8192** | Each entry becomes one CLI `--input`; empty strings **SHOULD** be rejected or ignored consistently with existing doctor mapping (Builder aligns with current handler). |
| `event_fields` | `persistence_list_run_events` | **256** | **256** | Top-level JSON key names only; generous for real allowlists. |

**Omitted / null arguments:** Optional parameters that are **`null`** or omitted **do not** trigger length checks. Bounds apply when the value is a **non-null** string or a **present** list.

**Structured error on violation:** Return **`status: "error"`** with **`replayt_surface: "bridge_input_bounds"`** (stable label) plus **`tool`**, **`message`**, **`correlation_id`** per [Error response shape](#error-response-shape). **`message` MUST NOT** include the full client-supplied string.

**Pytest bar (summary):** See [MISSION.md § JSON-schema bounds on high-risk string tool parameters (backlog spec)](MISSION.md#json-schema-bounds-on-high-risk-string-tool-parameters-backlog-spec) — over-limit + at-least-one at-limit success, no traceback in returned dict. Coverage: [`tests/test_mcp_tools.py`](../tests/test_mcp_tools.py) (`test_bridge_input_bounds_*`, `test_list_tools_input_schema_includes_string_bounds`).

Per-tool **Input shapes** tables below remain authoritative for **types** and **required** flags; **numeric bounds** are defined in this subsection. Each subsection that lists string or list parameters **MUST** point here so limits do not drift.

### `replayt_echo`

*Bounds:* [String parameter bounds (backlog spec)](#string-parameter-bounds-backlog-spec).

| Property | Type | Required |
| -------- | ---- | -------- |
| `message` | string | yes |

### `replayt_version_info`

No properties (empty object).

### `replayt_doctor`

*Bounds:* [String parameter bounds (backlog spec)](#string-parameter-bounds-backlog-spec).

| Property | Type | Required |
| -------- | ---- | -------- |
| `skip_connectivity` | boolean | no (default **`true`**) |
| `target` | string \| null | no |
| `strict_graph` | boolean | no (default `false`; only when **`target`** is set) |
| `inputs_json` | string \| null | no |
| `inputs_file` | string \| null | no |
| `input_overrides` | array of string \| null | no (each non-empty element becomes one CLI **`--input`**) |

### `workflow_contract_snapshot`

*Bounds:* [String parameter bounds (backlog spec)](#string-parameter-bounds-backlog-spec).

| Property | Type | Required |
| -------- | ---- | -------- |
| `target` | string | yes |

### `workflow_graph_mermaid`

*Bounds:* [String parameter bounds (backlog spec)](#string-parameter-bounds-backlog-spec).

| Property | Type | Required |
| -------- | ---- | -------- |
| `target` | string | yes |

### `runner_dry_run_plan`

*Bounds:* [String parameter bounds (backlog spec)](#string-parameter-bounds-backlog-spec).

| Property | Type | Required |
| -------- | ---- | -------- |
| `target` | string | yes |
| `inputs_json` | string \| null | no (JSON object text for the `inputs` slot in `replayt.cli.validation.validation_report`, when present) |
| `strict_graph` | boolean | no (default `false`; same as `validate_workflow_graph` / `validation_report` and CLI `--strict-graph`) |
| `metadata_json` | string \| null | no (JSON object text for `validation_report` `metadata_json`; default `null`) |
| `experiment_json` | string \| null | no (JSON object text for `validation_report` `experiment_json`; default `null`) |
| `policy_hook_context_json` | string \| null | no (JSON object text for `validation_report` `policy_hook_context_json`; default `null`) |

### Dry-check parity specification (runner_dry_run_plan)

This section refines **what “CLI parity” means** between the MCP tool and **`replayt run … --dry-check`** for integrators. It is derived from the **public Python entrypoints** the bridge calls (`replayt.cli.validation.validate_workflow_graph`, `validation_report`) and from **`replayt run … --dry-check`** in `replayt.cli.commands.run` within the declared **`replayt>=0.4.25,<0.5`** range.

**Handler behavior:** `runner_dry_run_plan` loads the target, runs `validate_workflow_graph(wf, strict_graph=…)`, then `validation_report` with the same `strict_graph`, `inputs_json`, `metadata_json`, `experiment_json`, and `policy_hook_context_json` values supplied by the client (omitted parameters use the defaults below, matching CLI defaults: `--strict-graph` off, optional JSON flags omitted).

**Target contract (additive MCP parameters only):** Each optional argument can be omitted; omission preserves the same defaults as before these parameters existed.

| MCP parameter | replayt API | `replayt run --dry-check` CLI |
| ------------- | ----------- | ------------------------------ |
| `strict_graph` (boolean, default `false`) | Same value passed to `validate_workflow_graph` and `validation_report` | `--strict-graph` |
| `metadata_json` (string \| null, default null) | `validation_report(..., metadata_json=…)` | `--metadata-json` |
| `experiment_json` (string \| null, default null) | `validation_report(..., experiment_json=…)` | `--experiment-json` |
| `policy_hook_context_json` (string \| null, default null) | `validation_report(..., policy_hook_context_json=…)` | `--policy-hook-context-json` (CLI may parse `@path` / `@-`; MCP hosts typically pass inline JSON object text) |

**Semantics:** Each `*_json` parameter is **JSON object text** (or `null`). Malformed or non-object JSON is surfaced as `status: "invalid"` via replayt’s report `errors` list (same pattern as `inputs_json` today). The bridge continues **not** to implement CLI-only ergonomics such as `@path` indirection or stdin reads for those strings unless explicitly specified later.

**Input resolution gap (documented, out of scope for this parity item):** The CLI merges `--inputs-json`, `--inputs-file`, repeatable `--input`, and project/env defaults through `resolve_run_inputs_json` before calling `validation_report`. The MCP tool exposes a **single** optional `inputs_json` string aligned with the **`inputs_json`** argument to `validation_report`, not the full CLI resolution stack. Closing that gap would require a **documented public helper** from replayt (or a deliberate bridge policy), not ad hoc duplication of CLI resolution.

**Backlog closure checks:**

1. `runner_dry_run_plan` exposes the four optional parameters with defaults matching prior hard-coded behavior (`strict_graph=false`, other JSON parameters `null`).
2. This document’s mapping row, input shapes table, and security table reflect the handler surface.
3. Pytest covers **at least one** knob that changes the outcome versus the default (`strict_graph=true` on a **trusted** two-state workflow file with no declared transitions; packaged `replayt_examples` targets in the supported range currently include transitions, so the contract test uses an on-disk `.py` workflow under `tmp_path`, same resolution path as `load_target` for files).

### `persistence_list_run_events`

*Bounds:* [String parameter bounds (backlog spec)](#string-parameter-bounds-backlog-spec).

| Property | Type | Required |
| -------- | ---- | -------- |
| `run_id` | string | yes |
| `store_hint` | string \| null | no (optional store path or typed hint for multi-backend setups; see [store_hint grammar](#store_hint-grammar)) |
| `event_fields` | array of string \| null | no (default `null`; see [Field allowlist semantics](#field-allowlist-semantics) below) |
| `max_events` | integer \| null | no (default `null`; see [Run event volume limits](#run-event-volume-limits-backlog-spec)) |
| `max_total_bytes` | integer \| null | no (default `null`; see [Run event volume limits](#run-event-volume-limits-backlog-spec)) |

### Field allowlist semantics

When **`event_fields`** is omitted or **`null`**, the bridge may still apply a **default** allowlist from **`REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`** (comma-separated top-level key names; see [SECURITY.md](SECURITY.md)). When **`event_fields`** is a **non-empty** array, those names are the allowlist for that call (**replacing** any env default). When **`event_fields`** is an **empty array** **`[]`**, no top-level allowlist is applied for that call (**overriding** an env default so integrators can still request full objects). Allowlisting applies only to **top-level** keys of **JSON object** events: each retained value (including nested objects) is left **unchanged**—secrets nested under an allowed key are **not** removed by this step. Non-object elements in **`events`** are returned unchanged. **`event_count`** remains the number of events loaded from the store, independent of filtering.

**Optional result redaction (operator policy):** By default the tool returns **`events`** as replayt’s store provides them (no bridge-side key walk) unless **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`** is truthy or an allowlist is in effect. When the process environment sets **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`** to a truthy token (**`1`**, **`true`**, **`yes`**, **`on`**, case-insensitive), the handler runs **`redact_structure`** on the **`events`** list **after** any top-level field selection, replacing values under dict keys that match the same sensitive-key substring list as structured stderr logging (`redact_structure` in `observability.py`—e.g. `api_key`, `password`, `token`). Nested dicts and lists are walked; this is **not** a complete PII or secret guarantee for arbitrary event shapes.

### Run event volume limits (backlog spec)

**Backlog title:** **Define hard caps for `persistence_list_run_events` volume** — bound worst-case **MCP response size** and typical **in-process memory** for the materialized event list returned to clients. **Implementation status:** handlers enforce the contract below; see [CHANGELOG.md](../CHANGELOG.md) **Unreleased** and [`tests/test_mcp_tools.py`](../tests/test_mcp_tools.py) (`test_persistence_list_run_events_volume_limit_*`).

**Trust model:** Persistence paths and `run_id` values remain **operator-trusted** (see [MISSION.md § Security and trust boundaries](MISSION.md#security-and-trust-boundaries)). Caps are **resource-protection defaults**, not a substitute for host tool policy or replayt-side hardening against hostile stores.

#### Caps (two independent axes)

Both checks apply to the **same snapshot** of the list returned by **`EventStore.load_events(run_id)`** (after a successful load, **before** top-level field allowlisting and **before** optional redaction):

1. **Event count** — `len(events)` **MUST NOT** exceed the effective **max events** limit.
2. **Total encoded size** — Let **`encoded`** be the UTF-8 byte length of a **compact JSON** serialization of that list (implementation **MUST** use a deterministic rule equivalent to Python **`json.dumps(events, separators=(',', ':'), ensure_ascii=False)`** on the loaded objects, or document any deliberate deviation). **`encoded`** **MUST NOT** exceed the effective **max total bytes** limit.

If **either** cap is exceeded, the tool **MUST NOT** return **`status: "ok"`** with a truncated list unless a **separate** backlog explicitly adopts partial-return semantics; today’s bar is a **hard stop** with a structured error.

#### Built-in defaults (when env is unset or invalid)

| Axis | Built-in default | Notes |
| ---- | ---------------- | ----- |
| Max events | **`10_000`** | Conservative for interactive MCP use; large legitimate runs require operator override. |
| Max total bytes | **`33_554_432`** (32 MiB) | Bounds approximate JSON payload size to the MCP client for the **`events`** array. |

Invalid or non-numeric env values **SHOULD** follow the same pattern as [Execution timeouts](#execution-timeouts): log a warning and fall back to the built-in default for that axis.

#### Environment variables (read only in `observability.py`)

| Variable | Semantics |
| -------- | --------- |
| **`REPLAYT_MCP_BRIDGE_RUN_EVENTS_MAX_COUNT`** | Optional **integer**. When **unset**, empty, or **invalid**, use the built-in **10_000** default. When set to **`0`** or a **negative** integer, **disable** the event-count cap for the process (operator opt-out; document operational risk). When set to a **positive** integer, that value is the effective default **max events** unless a per-invocation tool parameter overrides it. |
| **`REPLAYT_MCP_BRIDGE_RUN_EVENTS_MAX_TOTAL_BYTES`** | Optional **integer**. When **unset**, empty, or **invalid**, use the built-in **32 MiB** default. When **`0`** or **negative**, **disable** the byte cap. When **positive**, that value is the effective default **max total bytes** unless a per-invocation tool parameter overrides it. |

#### MCP tool parameters

Optional **`max_events`** and **`max_total_bytes`** (JSON integers or `null`):

- **`null`** (or omitted) — Use the effective limit from **env → built-in default** for that axis (after applying the disable rules above).
- **Positive integer** — Overrides the env/default effective limit for **this invocation only** (allows a **tighter** or **looser** cap per call than the process default).
- **Zero or negative** — **Invalid**; the tool **MUST** return a structured `{ "status": "error", … }` (no traceback in the dict) with a clear operational **`message`** (surface label below). **Do not** treat **`0`** on parameters as “unlimited” (unlimited remains **env-only**).

#### Error shape when a cap trips

The handler **MUST** return:

- `status: "error"`
- `tool: "persistence_list_run_events"`
- `replayt_surface: "bridge_run_events_volume"`
- `message` — Stable English text naming which limit failed (**event count** and/or **encoded size**), including the **effective limits** and, when practical, **observed** count and/or encoded size **without** embedding event bodies or large fragments.
- `correlation_id` — Same contract as [Error response shape](#error-response-shape); **MUST** match structured stderr for the invocation.

**MUST NOT:** Include a Python traceback in the returned dict for this mapped path.

**Stderr (SHOULD):** Emit a structured JSON log line (for example `replayt_mcp_bridge.run_events.volume_limit`) with **`correlation_id`**, which cap tripped, and numeric limits—**without** logging raw events or client-controlled strings beyond what is already normal for this tool.

#### Evaluation order and interaction with allowlist / redaction

Volume checks run on the **loaded** list **before** **`event_fields`** / **`REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`** filtering and **before** **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`**. Rationale: allowlisting could make a pathological run appear small on the wire while the process already paid decode/memory cost; the spec optimizes for **bounded handler work** on the materialized store output.

#### Known limitation (replayt API)

Today’s handler calls **`load_events`** and receives a full in-memory list. A **single** pathological event line could still stress memory **during** replayt’s load before these caps run. Closing that fully may require **upstream** replayt or store API support (streaming / per-line limits). After load, the bridge still enforces **count** and **encoded-size** caps on the materialized list so MCP responses and typical memory use stay bounded for **large numbers** of events.

#### Pytest / CI bar (run event volume limits)

1. **Over-limit fixture** — At least one test uses a **synthetic** JSONL (or SQLite, if simpler for the suite) store where **`load_events`** returns a list that **exceeds** the effective **max events** **or** produces an **`encoded`** length **above** the effective **max total bytes** (use **monkeypatch** on the store or handler boundary if that keeps CI deterministic).
2. **Assertions** — `status == "error"`, `replayt_surface == "bridge_run_events_volume"`, **`correlation_id`** present, and **no** traceback payload in the returned dict (same style as other mapped errors in [`tests/test_mcp_tools.py`](../tests/test_mcp_tools.py)).
3. **Optional** — Align stderr **`correlation_id`** with the tool result for the volume-limit path (covered by **`test_persistence_list_run_events_volume_limit_count_exceeded_correlates_logs`**).

#### Backlog closure checklist

- [x] Defaults (**10_000** events, **32 MiB** encoded), env vars, and tool parameters match this section and [SECURITY.md](SECURITY.md).
- [x] Mapped failure row present in [Mapped failure paths](#mapped-failure-paths-exception--branch-inventory).
- [x] Pytest meets [Pytest / CI bar (run event volume limits)](#pytest--ci-bar-run-event-volume-limits) above.

### store_hint grammar

Integrators may pass **`store_hint`** in several forms. Parsing is **additive**: legacy bare paths behave exactly as before typed prefixes existed.

| Form | Syntax | Resolution |
| ---- | ------ | ----------- |
| **Omitted** | `null` / omitted | `resolve_log_dir(DEFAULT_LOG_DIR)` (replayt project + env, same as omitting `--log-dir` style defaults in CLI tooling). |
| **Legacy path** | Any string that does **not** match a recognized typed prefix below (ASCII, case-insensitive keyword + first colon on the trimmed value) | `Path.expanduser`, then `Path.resolve(strict=False)`. If the suffix is `.sqlite` or `.db`, the path is opened as **SQLite**; else if it exists and is a **file**, return a structured error; otherwise treat it as a **JSONL log directory** path. |
| **Explicit legacy (`file:`)** | `file:` + path, when the hint does **not** begin with `file://` | Same **suffix heuristics** as a legacy bare path on the path part (after `expanduser` / `resolve`). Use this to force **opaque path** parsing when a future keyword might otherwise collide with the start of the string. **`file:///…` / `file://…` URIs** are **not** split: they remain legacy opaque strings (so `file:///tmp/x` is not mistaken for `file:` + `/tmp/x`). |
| **Typed JSONL directory** | `jsonl-dir:` + path or `jsonl:` + path | Same `expanduser` / `resolve` on the path part. Always use a **JSONL directory** store (never SQLite), even if the path ends in `.sqlite` / `.db` or the basename looks like a database file. If the path exists and is a **plain file**, return a structured error. The longer keyword **`jsonl-dir:`** is equivalent to **`jsonl:`**; prefer **`jsonl-dir:`** when documenting “directory-only” backends. |
| **Typed SQLite** | `sqlite:` + path | Same `expanduser` / `resolve` on the path part. Always open **SQLite** (read-only), **without** requiring a `.sqlite` / `.db` suffix—use this when the file name is ambiguous. |

**Prefix rules:** Keywords **`file:`** (except when followed by `//`), **`jsonl-dir:`**, **`jsonl:`**, and **`sqlite:`** are recognized, compared case-insensitively. **`jsonl-dir:`** is matched **before** **`jsonl:`** so the hyphenated form is not truncated. One ASCII colon ends the keyword (except `file://`, which is two slashes after the colon and keeps the whole string legacy). The path may be absolute or relative; optional leading whitespace after the first colon is stripped from the path part.

**Examples (POSIX-style paths; Windows accepts drive-qualified paths the same way):**

- Default logs: `store_hint` omitted.
- Legacy JSONL dir: `"/var/replayt/runs"` or `"~/project/.replayt/logs"`.
- Legacy SQLite file: `"/data/events.sqlite"`.
- Explicit legacy path (same heuristics as bare): `"file:/data/events.sqlite"` or `"file:C:\\logs\\store.sqlite"` (Windows).
- Explicit JSONL dir (disambiguate a directory whose name ends in `.sqlite`): `"jsonl-dir:/backups/archive.sqlite"` or `"jsonl:/backups/archive.sqlite"`.
- Explicit SQLite without conventional suffix: `"sqlite:/data/replayt-events"`.

## Error response shape

Target loading, persistence validation, and store resolution failures return a JSON object with **`status: "error"`** and operational fields (no Python traceback in the structured content for the **mapped** paths listed below).

### Current payload (released)

```json
{
  "status": "error",
  "tool": "<tool_name>",
  "replayt_surface": "<short mapping label>",
  "message": "…",
  "correlation_id": "<request_id or uuid4>"
}
```

### Specification: `correlation_id` (bounded structured errors backlog)

**Goal:** MCP client authors can quote a single identifier when reporting issues; operators find the same value in **structured stderr logs** for that tool invocation—without putting tracebacks in the tool result.

| Requirement | Detail |
| ----------- | ------ |
| **Tool result** | Every mapped operational error (same rows as [Mapped failure paths](#mapped-failure-paths-exception--branch-inventory)) **MUST** include a string field **`correlation_id`**. |
| **Stderr logs** | Every structured JSON log line emitted by the bridge for that **same invocation** (at minimum `replayt_mcp_bridge.tool.begin`, `replayt_mcp_bridge.tool.end`, `replayt_mcp_bridge.tool.unhandled_exception` when applicable, and bridge events such as `replayt_mcp_bridge.store_hint.rejected` that occur inside a tool handler) **MUST** include the **same** **`correlation_id`** value. |
| **Value** | If FastMCP exposes a non-empty `Context.request_id` for the call, **`correlation_id` MUST** reuse that string. Otherwise the bridge **MUST** generate a new UUID (version 4) once per tool entry and reuse it until the handler returns or raises. |

**Lifecycle (begin / end / error):** For every tool invocation, structured stderr **MUST** emit **`replayt_mcp_bridge.tool.begin`** before handler body work and, when the handler returns a dict (any `status`, including **`error`** from mapped paths), **`replayt_mcp_bridge.tool.end`** with the same **`correlation_id`** and the result **`status`**. If the handler raises an exception that is **not** mapped to a dict return, the wrapper **MUST** emit **`replayt_mcp_bridge.tool.unhandled_exception`** (same **`correlation_id`** as **`begin`**) and **MUST NOT** emit **`tool.end`** for that invocation—then re-raise. Mapped **`bridge_timeout`** and other mapped **`_tool_error`** returns are normal returns, so **`tool.end`** applies. This matches [`tools_common._log_replayt_tool_boundaries`](../src/replayt_mcp_bridge/tools_common.py).

**Implementation status:** Handlers return **`correlation_id`** on every mapped `{ "status": "error", … }` result. Structured stderr lines for the same invocation (`replayt_mcp_bridge.tool.begin` / `.end`, `.unhandled_exception` when applicable, and `replayt_mcp_bridge.store_hint.rejected`) include the **same** value. Optional **`mcp_request_id`** is still logged when FastMCP provides it (often identical to **`correlation_id`**).

### Acceptance criteria (refined, workflow phase 2)

Backlog **Return correlation ids on structured tool errors** — integrator-facing bar (see also [ARCHITECTURE.md § Architecture review: structured tool errors and correlation IDs](ARCHITECTURE.md#architecture-review-structured-tool-errors-and-correlation-ids)):

1. **Documented field** — This section (payload example, specification table, and mapped inventory) plus the architecture review cross-link define **`correlation_id`** for mapped `{ "status": "error", … }` results and stderr JSON. **Out of scope:** changing FastMCP transport-level errors.
2. **Result ↔ log alignment (tested)** — At least one mapped handler path is covered by pytest so the tool result and structured log lines for that invocation share the same **`correlation_id`** (see **`test_persistence_list_run_events_log_lock_error_correlates_logs`** and related cases in [`tests/test_mcp_tools.py`](../tests/test_mcp_tools.py); logging capture on `replayt_mcp_bridge.server`).
3. **Per-failing-request ids (spot check)** — When the bridge generates an id (no non-empty FastMCP `Context.request_id`), values are **UUID version 4** and **distinct invocations** receive **different** ids in ordinary use; pytest should assert **distinct** ids and **`uuid.UUID(…).version == 4`** where the suite covers synthesized ids (same module as (2)).

### Backlog spec: narrower unhandled-error mapping (replayt and SDK)

**Backlog title:** **Add correlation IDs and narrower unhandled-error mapping** — extends the earlier **Return correlation ids on structured tool errors** work by (a) locking the **lifecycle logging** contract above and (b) moving a **small, named** set of replayt (and, if justified, SDK) failures from the **unhandled** path into **`{ "status": "error", … }`** without broad `except Exception` handlers that hide bugs.

**Non-goals:** Do **not** map all `ReplaytError` subclasses blindly. Do **not** return structured errors for **programming mistakes** (`TypeError`, `AssertionError`, etc.) or for **unknown** exception types. Do **not** change FastMCP / MCP **transport** or JSON-RPC framing errors. Do **not** remove **`replayt_mcp_bridge.tool.unhandled_exception`** logging for exceptions that remain unmapped.

**Refined acceptance criteria (close-out bar for implementation + docs):**

1. **Correlation + lifecycle** — For every tool call, structured stderr includes **`replayt_mcp_bridge.tool.begin`** and (on normal completion, including mapped operational failure dicts) **`replayt_mcp_bridge.tool.end`**, each carrying the invocation’s **`correlation_id`**; unmapped raises emit **`replayt_mcp_bridge.tool.unhandled_exception`** with the **same** id, then propagate—per the **Lifecycle** paragraph and specification table above.
2. **At least one new mapped replayt family** — Extend [Mapped failure paths](#mapped-failure-paths-exception--branch-inventory) with **at least one** additional row for a **`replayt`** exception type (or a documented tuple of types) that is **not** already covered (`typer.BadParameter`, `ValueError` on `run_id`, `OSError`, `asyncio.TimeoutError` → `bridge_timeout`, etc.). Prefer types that are **operator-meaningful** on the current tool surface. **`replayt.LogLockError`** (JSONL store lock contention in [`replayt.persistence.jsonl`](https://pypi.org/project/replayt/)) is the **recommended first** mapping target for `persistence_list_run_events` / JSONL reads—Builder confirms the exact call stack and message shape against **replayt 0.4.25**.
3. **Tests** — Pytest proves the new row: structured tool result (`status: "error"`, **`correlation_id`**, no traceback in the returned dict) and **the same** **`correlation_id`** on captured **`tool.begin`** / **`tool.end`** lines for that scenario (pattern matches existing correlation tests in [`tests/test_mcp_tools.py`](../tests/test_mcp_tools.py)). Keep or extend coverage for **unmapped** propagation (shared id on **`begin`** + **`unhandled_exception`**, no silent swallow).
4. **Disclosure** — [SECURITY.md § Structured tool errors vs unhandled exceptions](SECURITY.md#structured-tool-errors-vs-unhandled-exceptions) and [ARCHITECTURE.md § Architecture review: correlation IDs and narrower unhandled-error mapping](ARCHITECTURE.md#architecture-review-correlation-ids-and-narrower-unhandled-error-mapping) stay aligned with the **exception stance table** above and the **mapped inventory** when this backlog closes.

**Replayt 0.4.x public exception surface (reference):** `replayt.ReplaytError` (base), `ApprovalPending`, `ContextSchemaError`, `LogLockError`, `RunFailed` — see upstream `replayt.exceptions`. The bridge **MCP tools are read-only introspection / persistence reads**; not every type is reachable. Builder **MUST** add a table row only where a tool **actually** invokes replayt code that can raise the type.

| Type | Typical replayt role | Mapping stance for this bridge (spec) |
| ---- | -------------------- | ------------------------------------- |
| `LogLockError` | JSONL log file lock failure | **Map** when raised on the `persistence_list_run_events` JSONL path; use a stable `replayt_surface` label (e.g. event store / JSONL lock) and `str(exc)` or a short sanitized message—**no** traceback in the tool dict. |
| `ContextSchemaError` | Step context violations (runner) | **Evaluate** per tool: map only if `workflow_contract_snapshot`, `workflow_graph_mermaid`, or `runner_dry_run_plan` can raise it on supported replayt versions; otherwise leave **unmapped** until a real path exists. |
| `RunFailed`, `ApprovalPending` | Run execution / human approval | **Out of scope** for current tools unless code review shows a reachable path from an MCP handler. |
| `ReplaytError` (base) | Catch-all semantic base | **Do not** map the base class alone; use **specific** subclasses in the inventory. |

**Propagated (not bridge `status: "error"`):** Any exception **not** listed in [Mapped failure paths](#mapped-failure-paths-exception--branch-inventory) follows [Unmapped exceptions (explicit)](#unmapped-exceptions-explicit). **MCP Python SDK / FastMCP** errors outside tool handler bodies (transport, protocol) are **out of scope** for this bridge’s structured error object.

### Mapped failure paths (exception / branch inventory)

These rows enumerate **mapped** routes to `{ "status": "error", … }` (including bridge timeout). Each such error **MUST** carry **`correlation_id`** per the specification above.

| MCP tool(s) | Trigger | Mechanism | Typical `replayt_surface` (handler) |
| ----------- | ------- | --------- | ------------------------------------- |
| `workflow_contract_snapshot`, `workflow_graph_mermaid`, `runner_dry_run_plan`, `persistence_list_run_events`, `replayt_doctor` | Handler exceeds **bridge** wall-clock budget | `asyncio.wait_for` (or equivalent) → mapped timeout result; see [Execution timeouts](#execution-timeouts) | `bridge_timeout` |
| `workflow_contract_snapshot`, `workflow_graph_mermaid`, `runner_dry_run_plan`, `persistence_list_run_events`, `replayt_doctor`, `replayt_echo` | String or list argument exceeds documented **maxLength** / **maxItems** ([String parameter bounds](#string-parameter-bounds-backlog-spec)) | FastMCP / Pydantic validates before the handler body; **`BridgeFastMCP.call_tool`** maps a **`ToolError`** whose cause is only Pydantic **`string_too_long`** or list **`too_long`** to **`_tool_error`** with a stable English **`message`** (no full argument echo); see [ARCHITECTURE.md](ARCHITECTURE.md) (**mcp_instance**) | `bridge_input_bounds` |
| `workflow_contract_snapshot` | Bad or unresolvable **target** | `typer.BadParameter` from `replayt.cli.targets.load_target` → `_tool_error` | `Workflow.contract + replayt.cli.targets.load_target` |
| `workflow_graph_mermaid` | Bad **target** | same | `replayt.graph_export.workflow_to_mermaid` |
| `runner_dry_run_plan` | Bad **target** | same (`load_target` before validation) | `replayt run --dry-check / validate_workflow_graph + validation_report` |
| `persistence_list_run_events` | Invalid **run_id** | `ValueError` from `replayt.persistence.jsonl.validate_run_id` → `_tool_error` | `EventStore.load_events (JSONL directory or SQLite file)` |
| `persistence_list_run_events` | **store_hint** points at a plain file that is not SQLite (legacy path rules) | `_resolve_persistence_paths` returns an error string → `_tool_error` | same |
| `persistence_list_run_events` | **store_hint** is `file:`, `jsonl-dir:`, `jsonl:`, or `sqlite:` with an **empty** path part | `_resolve_persistence_paths` returns an error string → `_tool_error` | same |
| `persistence_list_run_events` | **store_hint** `jsonl:…` / `jsonl-dir:…` resolves to an existing **file** | `_resolve_persistence_paths` returns an error string → `_tool_error` | same |
| `persistence_list_run_events` | Explicit **store_hint** rejected by **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** | branch → `_tool_error` (+ optional `replayt_mcp_bridge.store_hint.rejected` log) | same |
| `persistence_list_run_events` | SQLite path does not exist or is not a file | branch → `_tool_error` | same |
| `persistence_list_run_events` | Store open / read failure | `OSError` from `_open_read_store` / `load_events` → `_tool_error` | same |
| `persistence_list_run_events` | JSONL log file lock failure (contention / platform lock error) | `LogLockError` from `replayt.persistence.jsonl` during `load_events` on the JSONL store → `_tool_error` | `replayt.persistence.jsonl (JSONL log lock)` |
| `persistence_list_run_events` | Loaded events exceed **volume limits** (count and/or encoded size) | Bridge branch after `load_events` → `_tool_error`; see [Run event volume limits](#run-event-volume-limits-backlog-spec) | `bridge_run_events_volume` |
| `persistence_list_run_events` | Invalid **`max_events`** or **`max_total_bytes`** (for example **≤ 0** where the bridge validates before `load_events`) | Bridge validation → `_tool_error` | `EventStore.load_events (JSONL directory or SQLite file)` |
| `replayt_doctor` | Bad or unresolvable **`target`** (when provided) | `typer.BadParameter` from `replayt.cli.targets.load_target` → `_tool_error` | `replayt doctor + replayt.cli.targets.load_target` |
| `replayt_doctor` | **`OSError`** starting the subprocess | `_tool_error` | `replayt doctor (subprocess / parse)` |
| `replayt_doctor` | Empty stdout, **non-JSON** stdout, or JSON missing an expected **`replayt.doctor_report`** schema id | `_tool_error` (stderr tail may be included in **`message`**, truncated) | `replayt doctor (subprocess / parse)` |
| `replayt_echo` (gated inventory v1) | **`tools/call`** while **`REPLAYT_MCP_BRIDGE_DISABLE_DIAGNOSTIC_ECHO_TOOLS`** is truthy (or **`--no-diagnostic-echo-tools`** on the server entrypoint) | Bridge **`BridgeFastMCP.call_tool`** branch → `_tool_error` (does not run the echo handler or echo client arguments) | `bridge_diagnostic_tools_disabled` |

**Outside `status: "error"`:** `runner_dry_run_plan` graph/input validation failures use **`status: "invalid"`** and a `replayt.validate_report.v1` object in **`report`** (replayt-owned semantics).

### Unmapped exceptions (explicit)

Any **other** exception raised while executing a tool (for example an unexpected `RuntimeError` from replayt after `load_target` succeeds) is **not** converted to `{ "status": "error", … }`. The bridge logs `replayt_mcp_bridge.tool.unhandled_exception` (and a traceback via `logger.exception`), then **re-raises**; presentation to MCP clients depends on FastMCP / host behavior. **Tests** should keep at least one path where unmapped failures remain observable (e.g. handler tests that assert propagation or host-visible errors when the suite deliberately provokes them); do not widen `except Exception` without updating this table and adding focused tests.

To **narrow** this set, add explicit rows to [Mapped failure paths](#mapped-failure-paths-exception--branch-inventory) and follow [Backlog spec: narrower unhandled-error mapping](#backlog-spec-narrower-unhandled-error-mapping-replayt-and-sdk)—one **named** exception family at a time, with pytest and disclosure docs updated together.

## Success and validation shapes (MCP structured content)

Handlers return plain dicts that the MCP SDK serializes as structured tool content:

- **`status: "ok"`** — Normal completion (`replayt_echo`, `replayt_version_info`, successful contract/graph/persistence reads, successful **`replayt_doctor`** JSON parse—including when **`doctor.healthy`** is **`false`**).
- **`status: "invalid"`** — Used only by `runner_dry_run_plan` when the graph/inputs fail validation; the `report` field is a `replayt.validate_report.v1` object (same schema replayt uses for `--dry-check` style output).
- **`status: "error"`** — Expected operational failures (bad target, bad `run_id`, missing store, I/O errors, JSONL **`LogLockError`** on the mapped path, **`persistence_list_run_events` volume limits** per [Run event volume limits](#run-event-volume-limits-backlog-spec), documented **input length / list-size** caps → **`bridge_input_bounds`** per [Mapped failure paths](#mapped-failure-paths-exception--branch-inventory), **`replayt_echo`** when the [diagnostic echo gate](#backlog-spec-optional-omission-of-diagnostic-echo-tools-from-registration) is on) using the error object above—including **`correlation_id`** on mapped paths per [Error response shape](#error-response-shape)—not a substitute for MCP transport errors; **unhandled** exceptions may still propagate per SDK/host behavior.

For the **first end-to-end replayt milestone** (import + optional target resolution), see [MISSION.md § First replayt-backed tool calling](MISSION.md#first-replayt-backed-tool-calling-e2e-milestone).

## Backlog spec: `replayt_doctor` (MCP wrapper for `replayt doctor`)

**Backlog title:** Add an optional MCP tool wrapping `replayt doctor` for safe connectivity checks.  
**Implementation status:** **Registered** — handler in [`tools_health.py`](../src/replayt_mcp_bridge/tools_health.py); **subprocess** via **`sys.executable -m replayt doctor`** (argv list, **no** shell).

### Intent

Operators debugging attach and provider setup want **`replayt doctor`** diagnostics inside the MCP session. The upstream command can perform **outbound HTTP** (OpenAI-compatible **`OPENAI_BASE_URL` / `models` probe**) and **inspects credential-related environment**; the MCP tool **must not** enable network I/O unless the client explicitly opts out of the safe default, and docs **must** match replayt’s own CLI warnings.

### Replayt mapping

| Item | Specification |
| ---- | ------------- |
| **CLI / capability** | `replayt doctor` (Typer command). Use **`--format json`** so the bridge returns a machine-readable object (schema id **`replayt.doctor_report.v1`** in replayt **0.4.25**; treat as upstream-owned and version-guard in code if the shape drifts). |
| **Implementation (shipped)** | **`subprocess`**: **`asyncio.create_subprocess_exec`** with **`sys.executable`**, **`-m`**, **`replayt`**, **`doctor`**, plus mapped flags—**no** shell. Recorded in **`tools_health.py`** module docstring. |
| **Human text mode** | **Out of scope** for the MCP tool: hosts receive **structured JSON** only (`doctor` payload below), not raw Rich/text terminal output. |

### Parameters (MCP → CLI parity)

Defaults are chosen so **omitting all optional fields** matches a **safe** operator habit: **`replayt doctor --skip-connectivity --format json`** (no network probe for the default OpenAI-compat connectivity check).

| Property | Type | Required | Default | Semantics |
| -------- | ---- | -------- | ------- | --------- |
| `skip_connectivity` | boolean | no | **`true`** | When **`true`**, pass **`--skip-connectivity`** (no HTTP **`GET`** to **`OPENAI_BASE_URL`/models** and no API key sent for that probe). When **`false`**, omit **`--skip-connectivity`** so behavior matches a bare **`replayt doctor`** — **network I/O** and use of **`OPENAI_API_KEY`** (and related env) follow [replayt’s doctor documentation](https://pypi.org/project/replayt/) / packaged README security notes. |
| `target` | string \| null | no | `null` | When non-empty, pass **`--target`** using the same grammar as **`workflow_contract_snapshot`** (`load_target`). **Operator-trusted** input (import + file reads). |
| `strict_graph` | boolean | no | `false` | When **`target`** is set, pass **`--strict-graph`** when **`true`** (same as CLI). |
| `inputs_json` | string \| null | no | `null` | When set, pass **`--inputs-json`** for target preflight (JSON **object** text; malformed JSON follows replayt’s doctor / validate rules). |
| `inputs_file` | string \| null | no | `null` | When set, pass **`--inputs-file`** with the resolved path (filesystem read; operator-trusted). Bridge **does not** implement CLI **`@path`** / stdin indirection for this string unless a separate backlog explicitly adds it (same stance as [Dry-check parity specification](#dry-check-parity-specification-runner_dry_run_plan) for MCP JSON blobs). |
| `input_overrides` | array of string \| null | no | `null` | Each element is one **`key=value`** pair; map to repeated CLI **`--input`** in order (dotted keys allowed per upstream rules). |

**Explicit client action for network:** Setting **`skip_connectivity: false`** is the MCP equivalent of opting into **`replayt doctor`** without **`--skip-connectivity`**; integrators should treat it like running the CLI on an untrusted network only when **`OPENAI_BASE_URL`** and provider policy allow it.

### Success shape

On successful completion (doctor ran and produced parseable JSON):

```json
{
  "status": "ok",
  "tool": "replayt_doctor",
  "doctor": { "schema": "replayt.doctor_report.v1", "healthy": true, "checks": [] }
}
```

**Normative rules:**

- **`doctor`** **MUST** be the parsed **object** from replayt’s JSON doctor output (same keys upstream emits; do not strip **`checks`** entries for “privacy” unless a documented redaction pass is added in the same change-set).
- **`healthy: false`** inside **`doctor`** is still a **successful tool completion** — it means the environment failed a diagnostic, not that the MCP handler crashed. Optionally include **`replayt_exit_code`** (integer) when the implementation uses a subprocess so operators can correlate with CLI exit codes (replayt uses **non-zero** exits for unhealthy JSON runs per packaged CLI docs).
- **`tool`** key on success is **optional** but **recommended** for symmetry with error payloads and host logging.

### Structured errors

Use the standard object from [Error response shape](#error-response-shape) (`status: "error"`, `tool`, `replayt_surface`, `message`, `correlation_id`) for **mapped** operational failures, with **no Python traceback** in the returned dict for those paths.

The [Mapped failure paths](#mapped-failure-paths-exception--branch-inventory) table lists the shipped rows for **`replayt_doctor`**. They include at minimum:

| Trigger | Typical `replayt_surface` |
| ------- | ------------------------- |
| Bad **`target`** (Typer / `load_target`) | `replayt doctor + replayt.cli.targets.load_target` |
| Subprocess start failure, empty stdout, **non-JSON** stdout, or JSON missing the doctor schema id | `replayt doctor (subprocess / parse)` |
| Bridge **`asyncio.wait_for` timeout** | `bridge_timeout` |

**Unhandled** exceptions remain subject to [Unmapped exceptions (explicit)](#unmapped-exceptions-explicit).

### Execution timeouts

**`replayt_doctor`** is **Required** under [Tools in scope](#tools-in-scope). Per-tool env: **`REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_REPLAYT_DOCTOR_SECONDS`**.

### Security, logging, and redaction

- **No shell:** assemble **argv** only; never pass MCP strings through `/bin/sh` or `shell=True`.
- **Secrets:** The **`doctor`** object may reference **which** env vars exist or provider configuration (upstream **`checks`** entries). That is **not** a substitute for logging redaction: stderr remains subject to [SECURITY.md](SECURITY.md) rules (**no** full MCP argument payloads in structured logs). If the implementation logs auxiliary structured fields, run them through the same **`redact_structure`** path as other bridge logs.
- **Network column:** For [SECURITY.md § MCP tool capability tiers](SECURITY.md#mcp-tool-capability-tiers), **`replayt_doctor`** is **conditional**: **None** when **`skip_connectivity`** is **`true`** (default); **Outbound HTTP** (replayt-owned client to **`OPENAI_BASE_URL`**) when the client sets **`skip_connectivity: false`**.

### Pytest / CI bar

1. **Default collection — no network:** Default CI runs **`pytest -q -m "not network"`**; tests **MUST** pass with **`skip_connectivity` at default** (or **`true`**) so that job does not open outbound connections.
2. **Opt-in network:** Tests that set **`skip_connectivity: false`** carry **`@pytest.mark.network`** and are excluded unless pytest is invoked without that filter (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
3. **Coverage (shipped):** [`tests/test_mcp_tools.py`](../tests/test_mcp_tools.py) — happy path, bad **`target`**, non-JSON subprocess stdout, **`bridge_timeout`**, and an opt-in **`network`** test.

### Inventory rows (shipped)

**Builder checklist:**

- [x] Add **`replayt_doctor`** to the [Mapping: tool → replayt capability](#mapping-tool--replayt-capability) table.
- [x] Add input schema rows under [Input shapes (JSON Schema concepts)](#input-shapes-json-schema-concepts).
- [x] Add the security summary row beside other tools in [Security](#security) (this file).
- [x] Add the **MCP tool capability tiers** row in [SECURITY.md](SECURITY.md) and extend **`tests/test_security_docs.py`** (`test_security_doc_defines_tool_capability_tiers` tool tuple).
- [x] Add **`replayt_doctor`** to [Tools in scope](#tools-in-scope) for timeouts.

## Backlog spec: optional omission of diagnostic echo tools from registration

**Backlog title:** **Optional gated mode that omits diagnostic echo tools from registration**

**User story:** As a **deployer**, I want an **opt-in** switch so **`replayt_echo`** (and any **explicitly listed** similar pure echo/diagnostic tools) are **not** registered, reducing trivial exfiltration and trace-retention risk where MCP hosts log tool traffic.

**Context:** [SECURITY.md § MCP host and client logs](SECURITY.md#mcp-host-and-client-logs) and the **`replayt_echo`** tier row already warn that echo round-trips may be retained by hosts; this feature moves **enforcement to the bridge** when operators do not need wiring probes.

**Non-goals:** This is **not** a general “minimal tool profile” or workflow-only mode—**`replayt_version_info`**, **`replayt_doctor`**, workflow introspection, and persistence tools stay registered unless covered by **separate** backlog. This is **not** a substitute for host-side **`tools/call`** enforcement (see [SECURITY.md § Host-side partial tool exposure](SECURITY.md#host-side-partial-tool-exposure)).

### Configuration (normative)

| Control | Semantics |
| ------- | --------- |
| **Default** | Gate **off** — same tool surface as today (all bridge-defined tools registered). |
| **`REPLAYT_MCP_BRIDGE_DISABLE_DIAGNOSTIC_ECHO_TOOLS`** | Process environment. Gate **on** when the value is a case-insensitive truthy token: **`1`**, **`true`**, **`yes`**, **`on`**. Unset, empty, or any other value → gate **off**. |
| **`--no-diagnostic-echo-tools`** | Documented global flag on **`python -m replayt_mcp_bridge`** / **`replayt-mcp-bridge`**: sets the same semantics for the child server process before **`server`** import; **MUST** be mutually exclusive with **`health`**. Documented beside the env var in [SECURITY.md](SECURITY.md). |

**Read site:** Implemented in **`observability.py`** (`diagnostic_echo_tools_disabled`); the shared FastMCP app in **`mcp_instance.py`** subclasses **`BridgeFastMCP`** to filter **`tools/list`** and map gated **`tools/call`** names before handlers run.

### Gated tool inventory (v1)

| MCP tool name | Rationale |
| ------------- | --------- |
| **`replayt_echo`** | Pure client-text echo; no replayt dependency; highest signal-to-noise for “diagnostic only” removal. |

**Extensibility:** Adding a name to this set **REQUIRES** an update to this table, the [SECURITY.md](SECURITY.md) gate subsection, and tests. Do **not** treat “similar” tools as gated without listing them here.

### Behavioral requirements

1. **`tools/list`** — When the gate is **on**, the MCP advertised tool list **MUST NOT** include any name from the [Gated tool inventory](#gated-tool-inventory-v1).
2. **`tools/call`** — When the gate is **on** and the client requests a gated name, the bridge **MUST** return the standard structured error object from [Error response shape](#error-response-shape): **`status: "error"`**, **`tool`** equal to the requested name, **`replayt_surface: "bridge_diagnostic_tools_disabled"`**, a **stable English** **`message`** (e.g. that diagnostic echo tools are disabled by operator configuration—**no** echo of client arguments in the payload), and **`correlation_id`** per the same contract as other mapped errors. **MUST NOT** return **`status: "ok"`** with an **`echo`** field for gated names while the gate is on.
3. **Observability** — Prefer the same **begin/end** structured stderr pattern as other tool calls when the implementation still routes gated names through a bridge-controlled entry (see [Error response shape — Lifecycle](#error-response-shape)); if a future SDK path cannot emit **`tool.end`**, document the gap under [ARCHITECTURE.md](ARCHITECTURE.md) in the same change-set.
4. **Typo / unknown tool names** — Behavior for names that are **not** bridge-defined at all remains **SDK/host-defined**; this spec applies only to **known gated** names.

### Pytest / CI bar (implementation phase)

1. **Gate off (default)** — Assert **`replayt_echo`** appears in **`tools/list`** (or equivalent helper that mirrors registration), and an in-process or stdio **`tools/call`** returns the existing success shape (`status: "ok"`, echoed field).
2. **Gate on** — With **`REPLAYT_MCP_BRIDGE_DISABLE_DIAGNOSTIC_ECHO_TOOLS=true`** (or **`1`**), assert **`replayt_echo`** is **absent** from **`tools/list`**, and **`tools/call`** for **`replayt_echo`** returns **`status: "error"`** with **`replayt_surface: "bridge_diagnostic_tools_disabled"`**, **`correlation_id`** present, and **no** success echo payload.
3. **Default CI** — Both scenarios **MUST** run under **`pytest -q -m "not network"`** (no new network dependency). Prefer **subprocess** or **monkeypatched env** on the server module so registration is evaluated under each mode without flakiness.
4. **Stdio smoke** — [Stdio MCP session integration smoke test](MISSION.md#stdio-mcp-session-integration-smoke-test) already prefers **`replayt_version_info`**; keep default CI smoke **passing** without **`replayt_echo`** when the gate is **off**. If a test file explicitly relied on **`replayt_echo`** for wiring-only checks, document that it **MUST** set gate **off** or switch the happy-path tool to **`replayt_version_info`**.

### Builder checklist

- [x] Parse **`REPLAYT_MCP_BRIDGE_DISABLE_DIAGNOSTIC_ECHO_TOOLS`** (and **`--no-diagnostic-echo-tools`**) before the stdio server imports **`replayt_mcp_bridge.server`** (CLI sets env in **`__main__.py`**; env-only uses **`observability.py`** at request time).
- [x] Omit gated tools from **`tools/list`** when the gate is on; implement **`tools/call`** handling for gated names as specified (**`BridgeFastMCP`**).
- [x] Add the mapped failure row to [Mapped failure paths](#mapped-failure-paths-exception--branch-inventory) and keep [Success and validation shapes](#success-and-validation-shapes-mcp-structured-content) wording consistent.
- [x] Extend **`tests/test_security_docs.py`** / observability contract tests for the env string and helpers.
- [x] Update [SECURITY.md](SECURITY.md) **Environment variables** table and gate subsection (shipped wording).

## Security

**Selective exposure:** Operators choosing which tools to allow in a host config should start from the authoritative **[MCP tool capability tiers](SECURITY.md#mcp-tool-capability-tiers)** table in [SECURITY.md](SECURITY.md) (one row per tool, with suggested defaults for local vs shared environments). The per-tool filesystem notes below stay for quick reference beside schemas.

Tools that load workflow definitions or read event stores follow the **same trust model as running replayt locally** (see [MISSION.md](MISSION.md#security-and-trust-boundaries)). Concretely for this surface:

| Tool | Filesystem / code | Notes |
| ---- | ----------------- | ----- |
| `replayt_echo` | None | Reflected string only; harmless technically, but hosts should not treat echoed content as trusted if it is fed back into models or UIs. Bridge omits **`tools/list`** entry and maps **`tools/call`** when **`REPLAYT_MCP_BRIDGE_DISABLE_DIAGNOSTIC_ECHO_TOOLS`** is truthy or **`--no-diagnostic-echo-tools`** is used ([backlog spec](#backlog-spec-optional-omission-of-diagnostic-echo-tools-from-registration)). |
| `replayt_version_info` | None | Reads package metadata only. |
| `workflow_contract_snapshot` | **Yes** (via `load_target`) | Can import modules and read workflow files the server user can access—equivalent to `replayt contract` target resolution. |
| `workflow_graph_mermaid` | **Yes** (same as above) | Same target resolution as contract snapshot. |
| `runner_dry_run_plan` | **Yes** (target + optional JSON strings: `inputs_json`, `metadata_json`, `experiment_json`, `policy_hook_context_json`, and `strict_graph`) | Same trust model as passing those flags to `replayt run --dry-check`: resolves the target, validates graph/text only; no workflow execution or log writes. |
| `replayt_doctor` | **Optional** — **`target`** / **`inputs_file`** imply the same **`load_target`** / filesystem reads as **`replayt doctor`**; subprocess inherits the process environment | Default **`skip_connectivity: true`** avoids the OpenAI-compat HTTP probe; **`skip_connectivity: false`** enables replayt-owned outbound HTTP per upstream doctor docs. Returns structured **`doctor`** JSON (paths, env-var **names** in **`checks`**, provider hints)—treat like other diagnostics for logging and retention. |
| `persistence_list_run_events` | **Yes** (`store_hint`, default log dir) | Read-only store access; returns stored events **pass-through by default** (no top-level allowlist unless **`event_fields`**, **`REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`**, or redaction applies—see [Field allowlist semantics](#field-allowlist-semantics) and [SECURITY.md](SECURITY.md)). Integrators may pass **`event_fields`** or set **`REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`** to limit **top-level** keys only; nested content under kept keys is unchanged. Operators may set **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`** (truthy values per [SECURITY.md](SECURITY.md)) so **`events`** are copied through **`redact_structure`** after any allowlist step. Explicit hints may be legacy paths or typed prefixes **`file:`** / **`jsonl-dir:`** / **`jsonl:`** / **`sqlite:`** (see [store_hint grammar](#store_hint-grammar)). Operators may set **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** so explicit `store_hint` values outside configured roots are rejected with a structured error (default log-dir resolution when `store_hint` is omitted is unchanged). **Volume limits** (event count + compact JSON UTF-8 size after **`load_events`**, env + optional tool params, structured **`bridge_run_events_volume`** errors) are documented in [Run event volume limits](#run-event-volume-limits-backlog-spec) and enforced in **`tools_persistence.py`**. |

The bridge does **not** add shell indirection for these parameters. **Operators** should assume any connected MCP client can invoke **every tool the server advertises** in **`tools/list`** with arbitrary arguments permitted by the schemas; when the [diagnostic echo gate](#backlog-spec-optional-omission-of-diagnostic-echo-tools-from-registration) is on, that list excludes **`replayt_echo`** (while **`tools/call`** for that name still returns the mapped structured error).

**Operator guidance:** Required environment variables, “do not log” expectations, deployment patterns (local stdio vs shared host), and MCP host logging risks are documented in [docs/SECURITY.md](SECURITY.md).

**Error payloads:** Structured `{ status: error, tool, replayt_surface, message, correlation_id }` responses (mapped paths) may include filesystem paths or other operational detail in `message` (e.g. from `typer.BadParameter`, I/O errors). Treat them as visible to every attached client unless you filter at the host. Bridge stderr logs are JSON lines with tool name, **`correlation_id`**, optional MCP request id, and result status—not full MCP arguments—with redaction for sensitive-shaped keys (see [ARCHITECTURE.md § Observability](ARCHITECTURE.md#observability)). Operators can align client-reported ids with the same field in those logs. Deeper review notes live under [ARCHITECTURE.md § Security review (phase 6)](ARCHITECTURE.md#security-review-phase-6).
