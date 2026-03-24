# Security: secrets, environment, and trust boundaries

This document is for **operators and security reviewers** hosting the MCP bridge. It complements [MISSION.md § Security and trust boundaries](MISSION.md#security-and-trust-boundaries) and [ARCHITECTURE.md § Security review](ARCHITECTURE.md#security-review-phase-6).

For how **deployment and transport**, **MCP clients**, **secrets**, **inputs**, and **bridge tools** fit together, keep this table aligned with the mission’s trust-boundary narrative—especially **small tool surface**, **side effects** (filesystem, network, subprocesses), and treating **`target`** / persistence inputs as **operator-trusted** where the mission calls that out.

## MCP tool capability tiers

Use this table when deciding **which tools to register or block** in a given MCP host policy. The bridge does **not** ship compile-time registration flags today; exposure is entirely **host configuration**. For parameter-level semantics and replayt mapping, see [MCP_TOOLS.md](MCP_TOOLS.md).

| Tier | Tool | Filesystem (bridge / replayt) | Network (bridge-owned) | Trust implications | Suggested default — **local dev** | Suggested default — **shared workstation** |
| ---- | ---- | ----------------------------- | ------------------------ | ------------------ | --------------------------------- | ------------------------------------------ |
| **Diagnostic** | `replayt_echo` | None (returns the MCP `message` string) | None | Echoed content may be sensitive if clients or hosts log full tool traffic; not a filesystem probe. | Expose if useful for wiring checks | Expose only if host logging is trusted |
| **Diagnostic** | `replayt_version_info` | None (installed package metadata only) | None | Low sensitivity; confirms dependency resolution. | Expose | Expose |
| **Workflow introspection** | `workflow_contract_snapshot` | **Yes** — `load_target` can **import Python modules** and **read workflow files** the process can access (same story as `replayt contract` / `replayt run`) | None | **`target` is operator-trusted input**, not anonymous MCP input—see [MISSION.md § Security and trust boundaries](MISSION.md#security-and-trust-boundaries). Imported code may run import-time side effects. | Expose for trusted workspaces | Restrict or disable if clients/users pick untrusted targets |
| **Workflow introspection** | `workflow_graph_mermaid` | **Yes** — same **`target`** resolution as above | None | Same **target** and import semantics as the contract snapshot row above. | Expose for trusted workspaces | Restrict or disable if targets are untrusted |
| **Workflow introspection** | `runner_dry_run_plan` | **Yes** — **`target`** plus in-process parsing of optional JSON strings (`inputs_json`, `metadata_json`, `experiment_json`, `policy_hook_context_json`); **no** workflow execution or log writes | None | Same **`target`** trust as CLI **`replayt run --dry-check`**; large or hostile JSON is still parsed in-process. | Expose for trusted workspaces | Restrict or disable if targets or JSON sources are untrusted |
| **Persistence read** | `persistence_list_run_events` | **Yes** — read-only JSONL log **directory** or SQLite **file** via `store_hint` or replayt default log resolution (`expanduser` / resolved paths); optional **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** | None | Can return **historical run events** (often sensitive). Default pass-through; optional **`event_fields`** / **`REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`**, **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`**—see [Environment variables](#environment-variables) and [MCP_TOOLS.md § Field allowlist semantics](MCP_TOOLS.md#field-allowlist-semantics). | Expose when debugging your own runs | Often **disable** or pair with **roots**, **allowlists**, **redaction**, and strict client policy |

**Bridge code** (`replayt_mcp_bridge`) reads **`REPLAYT_MCP_BRIDGE_*`** variables only in **`observability.py`**: **`REPLAYT_MCP_BRIDGE_LOG_LEVEL`** (verbosity; not a secret); optionally **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** (comma-separated absolute paths that constrain explicit `store_hint` values on `persistence_list_run_events`—see below); optionally **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`** (opt-in key-based redaction of returned persistence events—see below); and optionally **`REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`** (default top-level field allowlist for `persistence_list_run_events` when the MCP client omits `event_fields`—see below). The process still inherits the full OS environment, and **replayt**, **Python**, **HTTP stacks**, and the **MCP parent** may read standard variables listed below.

## Host-side partial tool exposure

**Fixed registration surface (today):** Importing **`replayt_mcp_bridge.server`** loads **`tools_health`**, **`tools_workflow`**, and **`tools_persistence`**, which register **every** `@mcp.tool()` handler on the shared FastMCP app for the lifetime of the process. There is **no** supported flag, subcommand, or environment variable in this bridge to register only a subset of tools. **Narrowing exposure is therefore a host / operator responsibility**—use whatever your MCP client, gateway, or organizational policy provides.

**Patterns that usually work (host-dependent):**

- **Per-tool enablement** — Many hosts let operators turn individual tools on or off for a given server entry. Pair that with the [MCP tool capability tiers](#mcp-tool-capability-tiers) table: keep diagnostics where useful; disable workflow introspection and persistence reads when end users should not drive **`target`**, **`store_hint`**, or **`run_id`**.
- **Separate configurations or processes** — Maintain distinct MCP entries (or separate bridge processes under different OS accounts / **`cwd`** roots) for “full maintainer” vs “limited” use, when your toolchain can express it. The Python process still has whatever filesystem and environment rights the OS grants; hiding tools in the UI does **not** shrink those rights.
- **Layer bridge knobs for persistence only** — **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`**, **`REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`**, and **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`** constrain **`persistence_list_run_events`** (paths, top-level event keys, key-based redaction). They complement host policy but **do not replace** tool-level access control—see [Environment variables](#environment-variables).

**Residual risks — not fully fixable by “turning off” tools in the host UI:**

- **Enforcement vs presentation** — If the host only hides tools from prompts but still accepts `tools/call` for every registered name, a custom or compromised client could invoke “disabled” tools. Strong guarantees require the host (or an MCP gateway) to **reject disallowed calls on the wire**; this package does not ship that layer.
- **Path- and input-bearing `message` fields** — Structured `{ status: error, … }` results carry a **`message` string** built from replayt/Typer errors, bridge validation text, or `str(exc)` for some `OSError` paths. Examples in the current code include messages that embed **resolved filesystem paths** (e.g. missing SQLite file) or the **literal `store_hint`** for certain shape mistakes—useful for operators, but a **disclosure channel** if copied into logs or shown to untrusted clients. **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** denials are intentionally **generic** (no client path in the tool result or structured rejection log line); that behavior is **not** universal across all error branches—see [MCP_TOOLS.md § Error response shape](MCP_TOOLS.md#error-response-shape).
- **Unhandled exceptions** — Mapped failures avoid Python tracebacks **in the returned object** for covered paths; **unhandled** exceptions may still surface per FastMCP / SDK / host behavior and can leak different detail than structured errors.
- **Successful payloads** — Contract snapshots, Mermaid text, dry-check reports, and especially **persistence events** may contain secrets or PII under keys the bridge does not treat as sensitive. Combine host tool policy with [MCP host and client logs](#mcp-host-and-client-logs) discipline and the optional allowlist / redaction env vars above.

**Scope:** This section describes shipped behavior only. It does **not** claim authentication, dynamic tool registration, or host-side enforcement features that are not in this repository.

## Environment variables

Aside from the **`REPLAYT_MCP_BRIDGE_…`** variables implemented in **`observability.py`**, the bridge package does **not** define other `REPLAYT_MCP_*` knobs. It runs **in-process** with **replayt** and the **Python MCP SDK**, so the effective environment is:

1. **Whatever the MCP parent process inherits** (shell, IDE, agent runner, container image).
2. **Replayt’s configuration**, which combines project files (`.replaytrc.toml`, `pyproject.toml` `[tool.replayt]`) with several `REPLAYT_*` and related variables.

### Variables that commonly affect this bridge

| Variable | Role |
| -------- | ---- |
| `REPLAYT_MCP_BRIDGE_LOG_LEVEL` | Optional stdlib log level name for the `replayt_mcp_bridge` logger (default **`INFO`** if unset or invalid), e.g. `DEBUG` or `WARNING`. Read only in `observability.py`; does not carry secrets. |
| `REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS` | **Optional hardening.** When **unset** or **whitespace-only**, behavior matches releases before this feature: explicit `store_hint` paths are not restricted by the bridge (subject to normal validation). When set to a **non-empty** value, it must be **one or more absolute paths**, separated by **commas** (spaces after commas are trimmed). Each entry is expanded with `~` / user home rules, then resolved with `Path.resolve(strict=False)` the same way as `store_hint`. If **at least one** valid absolute root is parsed, every **explicit** `store_hint` on `persistence_list_run_events` must resolve to a path **equal to or under** one of those roots (using `Path.is_relative_to`); otherwise the tool returns the usual structured `{ status: error, … }` object **without** embedding the client-supplied hint in the message. **Omitted** `store_hint` (default log directory via replayt’s `resolve_log_dir`) is **not** checked against this list, so enabling the allowlist does not tighten default resolution. If the variable is non-empty but **no** valid absolute roots parse (e.g. only relative segments or `,,`), explicit `store_hint` is **rejected** with a generic configuration error. Read only in `observability.py`. |
| `REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS` | **Optional.** When **unset**, empty, or any value other than a case-insensitive **`1`**, **`true`**, **`yes`**, or **`on`**, `persistence_list_run_events` returns events **exactly as loaded** from the store (same pass-through default as before this knob existed—no extra structure traversal or copies for redaction). When set to one of those truthy tokens, the bridge applies **`redact_structure`** (same key-substring rules as structured stderr logs: e.g. `password`, `token`, `api_key`, `secret`, …) to the **`events`** list before returning it to MCP clients. This is a **best-effort** filter on JSON-shaped keys only; it does **not** replace full PII review, custom field policies, or restricting which clients may call the tool. Read only in `observability.py`. |
| `REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS` | **Optional default allowlist** for **`persistence_list_run_events`** when the MCP tool call **omits** the `event_fields` argument (or passes `null`). Comma-separated **top-level** JSON object keys (trimmed; empty segments ignored). When unset or only whitespace, there is **no** default allowlist—returned dict-shaped events stay **full pass-through** (subject to optional redaction above). When set to a non-empty list of names, each **object-shaped** event in **`events`** is reduced to **only those keys that exist** on the event (missing keys are omitted; this is **not** deep scrubbing—values under kept keys, including nested objects, are unchanged). A client may pass an **explicit empty array** `event_fields: []` to mean “no allowlist” and thereby **override** this env default for that call. If the client passes a **non-empty** `event_fields` list, it **replaces** the env default for that invocation. Read only in `observability.py`. |
| `REPLAYT_LOG_DIR` | When `persistence_list_run_events` is called **without** `store_hint`, replayt’s `resolve_log_dir` may use this (after project config) to locate the default JSONL run log directory. |
| `REPLAYT_TARGET` | Default workflow target for **replayt CLI** workflows of discovery; bridge tools usually pass `target` explicitly, but cwd-based config discovery still applies. |
| `REPLAYT_INPUTS_FILE` | Used by replayt CLI paths that read inputs from env; relevant if you extend tooling or share the same process environment with CLI wrappers. |
| `REPLAYT_FORBID_LOG_MODE_FULL` | Policy flag in replayt to reject full (unredacted) log modes on run-like entrypoints. |
| `REPLAYT_POLICY_HOOK_CONTEXT_JSON` | JSON context forwarded to trusted policy-hook subprocesses in replayt (not written to JSONL by replayt’s contract). |
| `REPLAYT_RUN_HOOK`, `REPLAYT_RESUME_HOOK`, … | Hook commands resolved from env in replayt when runs/resume/export paths execute (see replayt’s `run_support` / config docs). |
| `REPLAYT_JSONL_POSIX_MODE` | Optional portability toggle for JSONL persistence in replayt. |

### Examples: `REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`

- **Single root** — JSONL directories and SQLite files opened via explicit `store_hint` (legacy paths or `jsonl:` / `sqlite:` prefixes—see [MCP_TOOLS.md](MCP_TOOLS.md#store_hint-grammar)) must resolve under this tree:

  `REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS=/var/lib/replayt/persistence`

- **Multiple roots** (comma-separated; spaces after commas are ignored):

  `REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS=/data/replayt/logs,/archive/replayt/sqlite`

- **Windows** — use the same drive-qualified style you pass as `store_hint`, e.g. `REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS=C:\Data\replayt\logs`.

**Rejection logging:** When a hint is denied, the bridge logs **`replayt_mcp_bridge.store_hint.rejected`** with **`reason`** set to **`outside_allowlist`** or **`allowlist_unusable`**. It intentionally does **not** log the client `store_hint` value or the resolved filesystem path, so centralized telemetry is less likely to capture hostile probe strings.

### Credentials and LLM / API access (replayt)

The bridge **does not add** an authentication layer. If the **installed replayt** or a **workflow under inspection** uses model or HTTP APIs, replayt reads credentials from the environment the same way as the replayt CLI. Typical names include:

| Variable | Role |
| -------- | ---- |
| `OPENAI_API_KEY` | API key for OpenAI-compatible clients used by replayt’s LLM integration. |
| `OPENAI_BASE_URL` | Optional alternate API base URL (must not be logged with embedded secrets). |
| `REPLAYT_PROVIDER`, `REPLAYT_MODEL` | Provider and model selection for replayt LLM settings. |

Replayt also maintains an **audited list** of other provider API key names (presence-only checks for compliance-style reviews; values must never appear in logs). See `LLM_CREDENTIAL_ENV_VARS` in upstream replayt’s `replayt.security` module for the current set.

### Proxy and TLS trust (egress)

If replayt or dependencies perform HTTPS calls, standard proxy and trust variables may apply, for example `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `ALL_PROXY`, `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, and similar. Treat their **values** as sensitive where they embed credentials.

## MCP host and client logs

This package emits **one JSON object per line** on stderr for the `replayt_mcp_bridge` logger: `replayt_mcp_bridge.server.start`, `replayt_mcp_bridge.tool.begin` / `.end`, and error events include **`tool`**, **`correlation_id`**, result **`status`** (on success paths), and **`mcp_request_id`** when FastMCP provides a request context—never raw MCP tool arguments. Operators can match client-reported **`correlation_id`** values from mapped tool errors (see [MCP_TOOLS.md § Error response shape](MCP_TOOLS.md#error-response-shape)) to these stderr lines. Optional structured fields are passed through `redact_structure` in `observability.py` so common secret-like keys (e.g. `token`, `password`, `api_key`) are replaced with **`[REDACTED]`**. That does **not** limit what the **MCP host** records: many clients can trace or persist full JSON-RPC messages, including tool `arguments` and structured results. Misconfigured host logging is a common way **tokens, paths, and persistence payloads** leak into centralized telemetry.

- Prefer **disabled or minimized** MCP/protocol debug logging in production and on shared workstations.
- Treat **support bundles**, **crash reports**, and **IDE “share logs”** flows as untrusted until verified—they may contain full tool traffic.
- If you forward MCP-related logs to a vendor or SIEM, define **redaction or sampling** for tool parameters and results.

## What must never be logged

Operators and contributors should enforce these rules on **server logs**, **CI output**, and **shared telemetry**:

- **Secrets and credentials** — Never log values (or prefixes) of API keys, tokens, passwords, or private keys. This includes `OPENAI_API_KEY` and every name in replayt’s `LLM_CREDENTIAL_ENV_VARS`, webhook secrets, and signed URLs.
- **PII and sensitive workflow data** — Do not log contents of persistence events, full workflow inputs, or free-form dry-check JSON strings (`inputs_json`, `metadata_json`, `experiment_json`, `policy_hook_context_json`) / other tool arguments in production-style logs.
- **High-cardinality client input** — The bridge’s replayt-backed tools intentionally log only **tool name** and **outcome status** at info level, not MCP argument values. **Do not** change that to log `target`, `store_hint`, `run_id`, or raw JSON-RPC bodies at info level in environments where logs are broadly visible.
- **URLs with embedded secrets** — Strip userinfo and sensitive query parameters before logging URLs (replayt exposes helpers such as `sanitize_base_url_for_output` for base URLs).
- **Stack traces in shared logs** — `logger.exception` in the bridge may include paths and internal details; restrict log destinations accordingly. Structured tool errors returned to MCP clients intentionally avoid Python tracebacks for covered failure modes; unhandled exceptions may still propagate per host/SDK behavior.
- **Verbose MCP or JSON-RPC traces** — Full message bodies from hosts, proxies, or debug modes can duplicate secrets and PII that the bridge itself never writes to its own logger.

**MCP tool results:** By default, `persistence_list_run_events` returns stored events **as loaded** (pass-through). Integrators may pass **`event_fields`** (list of strings) to keep **only those top-level keys** on each object-shaped event, or set **`REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`** so the same allowlist applies when clients omit **`event_fields`**—see the environment table above. **Top-level filtering does not remove nested secrets** under keys you keep; combine with **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`** (truthy **`1`**, **`true`**, **`yes`**, **`on`**) if you want the bridge’s **`redact_structure`** walk on the result, or restrict clients and logging. Operators may set **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`** so the bridge returns a **redacted copy** (sensitive-shaped dict keys replaced with **`[REDACTED]`** per `redact_structure` in `observability.py`). **Redaction runs after** optional top-level field selection, so nested content under retained keys is still walked. Even then, payloads may contain sensitive data under non-matching key names; restrict which MCP clients and users may call that tool, and avoid echoing results into unsecured logging pipelines. The **`replayt_echo`** tool returns the client-supplied string unchanged to the MCP client—do not use it to shuttle secrets, and assume the host may retain that round-trip in traces.

## Recommended deployment pattern

| Pattern | When to use | Notes |
| ------- | ----------- | ----- |
| **Local stdio (recommended)** | IDE or agent spawns `replayt-mcp-bridge` or `python -m replayt_mcp_bridge` as a **child process** | Only the parent can speak MCP on stdin/stdout. Align with a threat model where the parent and workstation are trusted. |
| **Shared or remote host** | Team server, container, or socket-forwarded stdio | Any principal that can attach an MCP client or reach the forwarded transport can invoke **all** registered tools. There is **no** bridge-level authentication today—combine with network policy, mTLS, VPN, or host-only listeners as appropriate. |

The documented primary transport is **stdio**, not an HTTP listener owned by this package. Adding a remote-facing listener without hardening would increase exposure.

Copy-paste **host JSON** (Claude Desktop, Cursor, Zed, and similar) lives in **[MCP_HOST_CONFIG.md](MCP_HOST_CONFIG.md)**—stdio launch commands, **`cwd`** / workspace behavior for replayt discovery, and the **do not commit secrets** rule for **`env`** blocks.

## Reference documentation refresh (contributors)

The optional script [`scripts/refresh_replayt_reference_docs.py`](../scripts/refresh_replayt_reference_docs.py) is **not** part of the **`replayt_mcp_bridge`** import graph or **`[project.scripts]`** entry points: it is **maintainer tooling** run manually from a git checkout to populate [`docs/reference-documentation/`](reference-documentation/README.md). It performs **HTTPS** requests to **PyPI** (metadata JSON and the published **sdist** URL from that response) and unpacks **only** `README.md` and `LICENSE` from the tarball into a fixed under-`docs/` destination—see [ARCHITECTURE.md § Security review (phase 6)](ARCHITECTURE.md#security-review-phase-6) for trust notes and tarball handling. **Operators hosting the MCP server do not need to run it** for normal bridge operation.

## Interaction with replayt “auth”

Replayt does not replace organizational SSO for MCP. **API keys** and **provider credentials** are supplied via **environment** (and project config for non-secret settings) when features need them. The bridge:

- Does **not** read or store tokens for replayt separately.
- Does **not** redact persistence event bodies **by default**; optional **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`** enables key-based redaction on the MCP tool result (see the environment table above). Optional **`event_fields`** / **`REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`** limit **top-level** keys only (see the same table)—not a substitute for nested secret review.

For credential handling and redaction behavior inside replayt itself (log modes, redact keys, etc.), see upstream replayt documentation and config references.
