# Security: secrets, environment, and trust boundaries

This document is for **operators and security reviewers** hosting the MCP bridge. It complements [MISSION.md § Security and trust boundaries](MISSION.md#security-and-trust-boundaries) and [ARCHITECTURE.md § Security review](ARCHITECTURE.md#security-review-phase-6).

**Bridge code** (`replayt_mcp_bridge`) reads **`REPLAYT_MCP_BRIDGE_*`** variables only in **`observability.py`**: **`REPLAYT_MCP_BRIDGE_LOG_LEVEL`** (verbosity; not a secret) and, optionally, **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** (comma-separated absolute paths that constrain explicit `store_hint` values on `persistence_list_run_events`—see below). The process still inherits the full OS environment, and **replayt**, **Python**, **HTTP stacks**, and the **MCP parent** may read standard variables listed below.

## Environment variables

Aside from the **`REPLAYT_MCP_BRIDGE_…`** variables implemented in **`observability.py`**, the bridge package does **not** define other `REPLAYT_MCP_*` knobs. It runs **in-process** with **replayt** and the **Python MCP SDK**, so the effective environment is:

1. **Whatever the MCP parent process inherits** (shell, IDE, agent runner, container image).
2. **Replayt’s configuration**, which combines project files (`.replaytrc.toml`, `pyproject.toml` `[tool.replayt]`) with several `REPLAYT_*` and related variables.

### Variables that commonly affect this bridge

| Variable | Role |
| -------- | ---- |
| `REPLAYT_MCP_BRIDGE_LOG_LEVEL` | Optional stdlib log level name for the `replayt_mcp_bridge` logger (default **`INFO`** if unset or invalid), e.g. `DEBUG` or `WARNING`. Read only in `observability.py`; does not carry secrets. |
| `REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS` | **Optional hardening.** When **unset** or **whitespace-only**, behavior matches releases before this feature: explicit `store_hint` paths are not restricted by the bridge (subject to normal validation). When set to a **non-empty** value, it must be **one or more absolute paths**, separated by **commas** (spaces after commas are trimmed). Each entry is expanded with `~` / user home rules, then resolved with `Path.resolve(strict=False)` the same way as `store_hint`. If **at least one** valid absolute root is parsed, every **explicit** `store_hint` on `persistence_list_run_events` must resolve to a path **equal to or under** one of those roots (using `Path.is_relative_to`); otherwise the tool returns the usual structured `{ status: error, … }` object **without** embedding the client-supplied hint in the message. **Omitted** `store_hint` (default log directory via replayt’s `resolve_log_dir`) is **not** checked against this list, so enabling the allowlist does not tighten default resolution. If the variable is non-empty but **no** valid absolute roots parse (e.g. only relative segments or `,,`), explicit `store_hint` is **rejected** with a generic configuration error. Read only in `observability.py`. |
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

**MCP tool results:** `persistence_list_run_events` returns stored events **as-is**. Those payloads may contain secrets or PII. Restrict which MCP clients and users may call that tool, and avoid echoing results into unsecured logging pipelines. The **`replayt_echo`** tool returns the client-supplied string unchanged to the MCP client—do not use it to shuttle secrets, and assume the host may retain that round-trip in traces.

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
- Does **not** redact persistence event bodies before returning them to MCP clients.

For credential handling and redaction behavior inside replayt itself (log modes, redact keys, etc.), see upstream replayt documentation and config references.
