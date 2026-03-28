# MCP tools (initial surface)

This bridge exposes a small, versioned set of MCP tools that map to **replayt** APIs or CLI workflows. **Input schemas stay stable** so clients can integrate early; workflow, dry-check, and persistence tools call replayt in-process (handlers in `src/replayt_mcp_bridge/tools_*.py`, registered when `server.py` imports those modules). For process boundaries and how tools sit above replayt, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Execution timeouts

**Problem:** Handlers call replayt **in-process**. Without a bridge-level wall-clock policy, a single stuck call can block the whole MCP stdio session.

**Approach:** Apply an **outer** `asyncio.wait_for` (or equivalent) around the async body of each **in-scope** tool (see [Tools in scope](#execution-timeouts-tools-in-scope)). This is **in addition to** any timeouts inside replayt (HTTP clients, hooks, etc.); upstream behavior is not reimplemented here.

### Configuration and precedence

- **Units:** Non-negative **floating-point seconds** (fractional values allowed, e.g. `0.1`).
- **Parsing:** Non-numeric values, empty strings, or values **`≤ 0`** at a given step are treated as described below. Implementations **SHOULD** log a warning when a value is invalid and ignored.
- **Read site:** All `REPLAYT_MCP_BRIDGE_*` timeout variables are read only in `observability.py`, consistent with other bridge env knobs ([SECURITY.md](SECURITY.md)).

**Precedence (highest wins):**

1. **`REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_<TOOL>_SECONDS`** — Per-tool override. **`<TOOL>`** is the MCP tool name in **ASCII uppercase with underscores**, matching the registered name exactly (e.g. `REPLAYT_MCP_BRIDGE_TOOL_TIMEOUT_WORKFLOW_CONTRACT_SNAPSHOT_SECONDS`, `…_RUNNER_DRY_RUN_PLAN_SECONDS`, `…_PERSISTENCE_LIST_RUN_EVENTS_SECONDS`). When set and **strictly > 0** after parsing, this is the wall-clock budget for that tool.
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
| `replayt_echo` | _(bridge only)_ | Proves MCP wiring; echoes input. |
| `replayt_version_info` | `replayt.__version__` / `replayt.__version_tuple__` | Reads installed replayt via the same helpers as `replayt_mcp_bridge.installed_replayt_version`. |
| `workflow_contract_snapshot` | `Workflow.contract()`, via `replayt.cli.targets.load_target` | Same **target** grammar as `replayt contract` / `replayt run` (e.g. `module.path:wf`, `workflow.py`). Returns `{ status, target, contract }` or `{ status: error, tool, replayt_surface, message }`. Subject to [Execution timeouts](#execution-timeouts). |
| `workflow_graph_mermaid` | `replayt.graph_export.workflow_to_mermaid` | Aligns with `replayt graph` Mermaid output. Returns `{ status, target, mermaid }` or an error object. Subject to [Execution timeouts](#execution-timeouts). |
| `runner_dry_run_plan` | `replayt run --dry-check` (graph validation + `validation_report`) | Validates graph and optional JSON strings without executing steps or writing logs. Returns `{ status: ok \| invalid, report }` matching `replayt.validate_report.v1`, or an error object. Optional `strict_graph` and `metadata_json` / `experiment_json` / `policy_hook_context_json` match the CLI `--dry-check` knobs; defaults and gaps are documented under [Dry-check parity specification (runner_dry_run_plan)](#dry-check-parity-specification-runner_dry_run_plan). Subject to [Execution timeouts](#execution-timeouts). |
| `persistence_list_run_events` | `EventStore.load_events` on JSONL log dir or SQLite DB | `store_hint`: omit for project-resolved default log dir (`resolve_log_dir(DEFAULT_LOG_DIR)`), or pass a legacy filesystem path (JSONL **directory** or `.sqlite` / `.db` file per suffix heuristics), or an explicit typed hint (`file:…`, `jsonl-dir:…`, `jsonl:…`, `sqlite:…`—see [store_hint grammar](#store_hint-grammar)). Optional env **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** (see [SECURITY.md](SECURITY.md)) restricts **explicit** `store_hint` paths to resolved locations under listed absolute roots. Optional **`event_fields`** (list of strings): when non-empty, each **object-shaped** event keeps **only those top-level keys** that exist on the event; omit, `null`, or **`[]`** means no MCP-level allowlist for that call (see [Field allowlist semantics](#field-allowlist-semantics)). Optional env **`REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`** supplies a **default** comma-separated allowlist when **`event_fields`** is omitted or `null`; explicit **`event_fields: []`** overrides that default to “no allowlist.” Optional env **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`** (truthy: **`1`**, **`true`**, **`yes`**, **`on`**) applies **`redact_structure`** **after** any top-level field selection. Default for existing callers remains full pass-through when those knobs are unset. Returns `{ status, run_id, event_count, events, store }` or an error object. Subject to [Execution timeouts](#execution-timeouts). |

## Input shapes (JSON Schema concepts)

Tools are registered with the official Python MCP SDK (`mcp.server.fastmcp`); hosts receive JSON Schema derived from the Python signatures below.

### `replayt_echo`

| Property | Type | Required |
| -------- | ---- | -------- |
| `message` | string | yes |

### `replayt_version_info`

No properties (empty object).

### `workflow_contract_snapshot`

| Property | Type | Required |
| -------- | ---- | -------- |
| `target` | string | yes |

### `workflow_graph_mermaid`

| Property | Type | Required |
| -------- | ---- | -------- |
| `target` | string | yes |

### `runner_dry_run_plan`

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

| Property | Type | Required |
| -------- | ---- | -------- |
| `run_id` | string | yes |
| `store_hint` | string \| null | no (optional store path or typed hint for multi-backend setups; see [store_hint grammar](#store_hint-grammar)) |
| `event_fields` | array of string \| null | no (default `null`; see [Field allowlist semantics](#field-allowlist-semantics) below) |

### Field allowlist semantics

When **`event_fields`** is omitted or **`null`**, the bridge may still apply a **default** allowlist from **`REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`** (comma-separated top-level key names; see [SECURITY.md](SECURITY.md)). When **`event_fields`** is a **non-empty** array, those names are the allowlist for that call (**replacing** any env default). When **`event_fields`** is an **empty array** **`[]`**, no top-level allowlist is applied for that call (**overriding** an env default so integrators can still request full objects). Allowlisting applies only to **top-level** keys of **JSON object** events: each retained value (including nested objects) is left **unchanged**—secrets nested under an allowed key are **not** removed by this step. Non-object elements in **`events`** are returned unchanged. **`event_count`** remains the number of events loaded from the store, independent of filtering.

**Optional result redaction (operator policy):** By default the tool returns **`events`** as replayt’s store provides them (no bridge-side key walk) unless **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`** is truthy or an allowlist is in effect. When the process environment sets **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`** to a truthy token (**`1`**, **`true`**, **`yes`**, **`on`**, case-insensitive), the handler runs **`redact_structure`** on the **`events`** list **after** any top-level field selection, replacing values under dict keys that match the same sensitive-key substring list as structured stderr logging (`redact_structure` in `observability.py`—e.g. `api_key`, `password`, `token`). Nested dicts and lists are walked; this is **not** a complete PII or secret guarantee for arbitrary event shapes.

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
2. **Result ↔ log alignment (tested)** — At least one mapped handler path is covered by pytest so the tool result and structured log lines for that invocation share the same **`correlation_id`** (see [`tests/test_mcp_tools.py`](../tests/test_mcp_tools.py) and logging capture on `replayt_mcp_bridge.server`).
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
| `workflow_contract_snapshot`, `workflow_graph_mermaid`, `runner_dry_run_plan`, `persistence_list_run_events` | Handler exceeds **bridge** wall-clock budget | `asyncio.wait_for` (or equivalent) → mapped timeout result; see [Execution timeouts](#execution-timeouts) | `bridge_timeout` |
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

**Outside `status: "error"`:** `runner_dry_run_plan` graph/input validation failures use **`status: "invalid"`** and a `replayt.validate_report.v1` object in **`report`** (replayt-owned semantics).

### Unmapped exceptions (explicit)

Any **other** exception raised while executing a tool (for example an unexpected `RuntimeError` from replayt after `load_target` succeeds) is **not** converted to `{ "status": "error", … }`. The bridge logs `replayt_mcp_bridge.tool.unhandled_exception` (and a traceback via `logger.exception`), then **re-raises**; presentation to MCP clients depends on FastMCP / host behavior. **Tests** should keep at least one path where unmapped failures remain observable (e.g. handler tests that assert propagation or host-visible errors when the suite deliberately provokes them); do not widen `except Exception` without updating this table and adding focused tests.

To **narrow** this set, add explicit rows to [Mapped failure paths](#mapped-failure-paths-exception--branch-inventory) and follow [Backlog spec: narrower unhandled-error mapping](#backlog-spec-narrower-unhandled-error-mapping-replayt-and-sdk)—one **named** exception family at a time, with pytest and disclosure docs updated together.

## Success and validation shapes (MCP structured content)

Handlers return plain dicts that the MCP SDK serializes as structured tool content:

- **`status: "ok"`** — Normal completion (`replayt_echo`, `replayt_version_info`, successful contract/graph/persistence reads).
- **`status: "invalid"`** — Used only by `runner_dry_run_plan` when the graph/inputs fail validation; the `report` field is a `replayt.validate_report.v1` object (same schema replayt uses for `--dry-check` style output).
- **`status: "error"`** — Expected operational failures (bad target, bad `run_id`, missing store, I/O errors) using the error object above—including **`correlation_id`** on mapped paths per [Error response shape](#error-response-shape)—not a substitute for MCP transport errors; **unhandled** exceptions may still propagate per SDK/host behavior.

For the **first end-to-end replayt milestone** (import + optional target resolution), see [MISSION.md § First replayt-backed tool calling](MISSION.md#first-replayt-backed-tool-calling-e2e-milestone).

## Security

**Selective exposure:** Operators choosing which tools to allow in a host config should start from the authoritative **[MCP tool capability tiers](SECURITY.md#mcp-tool-capability-tiers)** table in [SECURITY.md](SECURITY.md) (one row per tool, with suggested defaults for local vs shared environments). The per-tool filesystem notes below stay for quick reference beside schemas.

Tools that load workflow definitions or read event stores follow the **same trust model as running replayt locally** (see [MISSION.md](MISSION.md#security-and-trust-boundaries)). Concretely for this surface:

| Tool | Filesystem / code | Notes |
| ---- | ----------------- | ----- |
| `replayt_echo` | None | Reflected string only; harmless technically, but hosts should not treat echoed content as trusted if it is fed back into models or UIs. |
| `replayt_version_info` | None | Reads package metadata only. |
| `workflow_contract_snapshot` | **Yes** (via `load_target`) | Can import modules and read workflow files the server user can access—equivalent to `replayt contract` target resolution. |
| `workflow_graph_mermaid` | **Yes** (same as above) | Same target resolution as contract snapshot. |
| `runner_dry_run_plan` | **Yes** (target + optional JSON strings: `inputs_json`, `metadata_json`, `experiment_json`, `policy_hook_context_json`, and `strict_graph`) | Same trust model as passing those flags to `replayt run --dry-check`: resolves the target, validates graph/text only; no workflow execution or log writes. |
| `persistence_list_run_events` | **Yes** (`store_hint`, default log dir) | Read-only store access; returns stored events **pass-through by default** (no top-level allowlist unless **`event_fields`**, **`REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`**, or redaction applies—see [Field allowlist semantics](#field-allowlist-semantics) and [SECURITY.md](SECURITY.md)). Integrators may pass **`event_fields`** or set **`REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`** to limit **top-level** keys only; nested content under kept keys is unchanged. Operators may set **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`** (truthy values per [SECURITY.md](SECURITY.md)) so **`events`** are copied through **`redact_structure`** after any allowlist step. Explicit hints may be legacy paths or typed prefixes **`file:`** / **`jsonl-dir:`** / **`jsonl:`** / **`sqlite:`** (see [store_hint grammar](#store_hint-grammar)). Operators may set **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** so explicit `store_hint` values outside configured roots are rejected with a structured error (default log-dir resolution when `store_hint` is omitted is unchanged). |

The bridge does **not** add shell indirection for these parameters. **Operators** should assume any connected MCP client can invoke all registered tools with arbitrary arguments permitted by the schemas.

**Operator guidance:** Required environment variables, “do not log” expectations, deployment patterns (local stdio vs shared host), and MCP host logging risks are documented in [docs/SECURITY.md](SECURITY.md).

**Error payloads:** Structured `{ status: error, tool, replayt_surface, message, correlation_id }` responses (mapped paths) may include filesystem paths or other operational detail in `message` (e.g. from `typer.BadParameter`, I/O errors). Treat them as visible to every attached client unless you filter at the host. Bridge stderr logs are JSON lines with tool name, **`correlation_id`**, optional MCP request id, and result status—not full MCP arguments—with redaction for sensitive-shaped keys (see [ARCHITECTURE.md § Observability](ARCHITECTURE.md#observability)). Operators can align client-reported ids with the same field in those logs. Deeper review notes live under [ARCHITECTURE.md § Security review (phase 6)](ARCHITECTURE.md#security-review-phase-6).
