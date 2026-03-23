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
| Runner (dry) | `runner_dry_run_plan` | Graph validation plus `validation_report` aligned with `replayt run --dry-check`; optional `inputs_json` string. |
| Persistence read | `persistence_list_run_events` | Read-only access to events via JSONL log directory or SQLite path; default log dir matches CLI resolution when `store_hint` is omitted. |

## Shared implementation patterns

- **Structured errors:** Operational failures that should reach the client as data use `_tool_error(...)` → `{ status: "error", tool, replayt_surface, message }`. `typer.BadParameter` from `load_target` and invalid run IDs are mapped this way instead of leaking stack traces across the MCP boundary.
- **Persistence resolution:** `_resolve_persistence_paths` interprets `store_hint` (default dir, JSONL directory, or `.sqlite`/`.db` file). `_open_read_store` yields a read-only store for `load_events`.
- **Schema stability:** Tool inputs are plain Python parameters on `@mcp.tool()` functions; hosts receive JSON Schema derived by FastMCP. Prefer additive optional parameters over breaking renames.

## Observability

- **Configuration:** `configure_bridge_logging()` (from `observability.py`) runs at server startup: stderr handler, default level **`INFO`**, overridable via **`REPLAYT_MCP_BRIDGE_LOG_LEVEL`** (the only `os.environ` read in this package).
- **Server lifecycle:** `run_stdio()` emits structured `replayt_mcp_bridge.server.start` with `transport: stdio` once before blocking on the MCP run loop.
- **Tools:** `_log_replayt_tool_boundaries` wraps every registered handler (including `replayt_echo`) and emits JSON lines for `replayt_mcp_bridge.tool.begin` / `.end` with **`tool`**, optional **`mcp_request_id`** from FastMCP `Context`, and result **`status`** on completion. Client argument values are never included. Extra structured fields are redacted via `redact_structure` before emission.
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

- **Phase 5 (architecture review):** Documented under [Architecture review (phase 5)](#architecture-review-phase-5) below—**declared replayt range**, integrator-facing docs, **`replayt-floor`** CI, and **version/doc contract tests** stay aligned (backlog: compatibility matrix and CHANGELOG).
- **Phase 6 (security review):** `server.py` was reviewed against [MISSION.md](MISSION.md#security-and-trust-boundaries) and the [MCP_TOOLS.md](MCP_TOOLS.md) security table; findings are summarized in [Security review (phase 6)](#security-review-phase-6) below. No handler changes were required for the stated stdio / trusted-operator model; CI gained explicit read-only `contents` permissions; optional hardenings remain follow-ups.
- **Parity:** `runner_dry_run_plan` currently fixes `strict_graph=False` and omits optional JSON blobs that the CLI may accept; exposing them as optional MCP parameters is a backward-compatible extension.
- **Persistence hints:** Path/suffix heuristics work for JSONL dirs vs SQLite files; a structured `store_hint` (e.g. typed URI prefixes) would be a separate, explicit contract change.
- **Event privacy:** Returned events are replayt’s stored JSON as-is; any redaction policy belongs in docs and optional bridge-level filtering if integrators require it.

### Architecture review (phase 5)

**Scope:** Backlog **“Add compatibility matrix and CHANGELOG for replayt releases”**—confirm how **integrators** learn supported replayt versions stays coherent: one **declared** PEP 440 range in packaging, mirrored in human docs, exercised at the **lower bound** in CI, and guarded by **pytest** so edits cannot drift silently.

**Single source of truth:** `[project].dependencies` in [`pyproject.toml`](../pyproject.toml) holds the **`replayt`** constraint (today `replayt>=0.4.25,<0.5`). Install resolution and downstream metadata derive from that line—not from README prose alone.

**Integrator surfaces (intentional duplication):**

- **[README.md](../README.md)** — **Compatibility with replayt** repeats the **exact** dependency line from `pyproject.toml` and a small **bridge version × declared range × CI-tested floor** table so upgrades are plannable without opening packaging files.
- **[CHANGELOG.md](../CHANGELOG.md)** — Keep a Changelog sections; each release notes user-visible bridge changes and references the declared replayt range when it matters to consumers.
- **[CONTRIBUTING.md](../CONTRIBUTING.md) § Releases** — One paragraph tying **version bump**, **changelog**, **`pyproject.toml`**, **README** table, **`replayt-floor`** pin in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), green CI, and **git tag**.
- **[DESIGN_PRINCIPLES.md](DESIGN_PRINCIPLES.md) § replayt version contract** — Long-form policy (range vs pin, tracking upstream, Windows venv note); must quote the same range as `pyproject.toml` for discoverability.

**CI boundary:** Besides the default matrix (latest **replayt** compatible with the declared range), the **`replayt-floor`** job reinstalls **`replayt=={minimum}`** after `pip install -e ".[dev]"` so the **lower bound** is not only documented but **tested** against the same suite as the default job.

**Automation:** [`tests/test_version_contract_docs.py`](../tests/test_version_contract_docs.py) parses `pyproject.toml` and asserts README, CHANGELOG, CONTRIBUTING, CI, and DESIGN_PRINCIPLES stay consistent with the declared range and `[project].version`. Tests use a literal `_EXPECTED_REPLAYT_SPEC` alongside `pyproject.toml` so a partial bump fails loudly (update the constant and docs together). Floor parsing today expects a **`>=x.y.z`** patch triple; a more exotic constraint string would need a richer parser.

**Residual / extension rules:** When the minimum or range changes, update **`pyproject.toml`**, **README**, **CHANGELOG**, **CONTRIBUTING**, **DESIGN_PRINCIPLES** (if the narrative changes), **CI** `replayt-floor` reinstall and job label, and **`_EXPECTED_REPLAYT_SPEC`** in the contract tests in one maintainer pass. **Structured logging** and MCP trust-boundary architecture remain under [Observability](#observability) and [Security review (phase 6)](#security-review-phase-6).

### Security review (phase 6)

**Scope:** Security pass on **`server.py`** (tool surface and dispatch) against [MISSION.md](MISSION.md#security-and-trust-boundaries) and the security table in [MCP_TOOLS.md](MCP_TOOLS.md), plus **`observability.py`** for the structured-logging / redaction contract tied to backlog **“Ship structured logging with redaction hooks.”**

**Observability (`observability.py`):** `emit_json_log` runs caller fields through **`redact_structure`** (case-insensitive key substrings: password, secret, token, api_key, etc.) before `json.dumps`; values under non-matching keys are unchanged—same residual as phase 5. **`REPLAYT_MCP_BRIDGE_LOG_LEVEL`** is the sole in-package `os.environ` read (verbosity only; invalid names fall back to **INFO**). `configure_bridge_logging` attaches one stderr `StreamHandler` with `%(message)s`, **`propagate=False`** on `replayt_mcp_bridge` to avoid duplicate root handlers, and does not log environment values. `json.dumps(..., default=str)` is a last resort for non-JSON-native field values; current bridge emissions use JSON-safe primitives.

**Phase 6 close-out:** Re-checked `server.py` and `observability.py` against the tables and docs above. Dispatch remains replayt/`pathlib` only (no shell or subprocess for MCP args); `_log_replayt_tool_boundaries` still omits tool arguments from log payloads; contract tests (`test_security_docs.py`, `test_observability.py`, `test_mcp_tools.py`) still enforce the env-read surface and redaction. No code changes were required; findings below are unchanged aside from the explicit observability verification.

**Transport and process:** The documented entrypath remains **stdio-only**; the bridge does not open its own network listeners. Whoever controls the parent process (or can substitute stdio) can invoke tools—treat MCP attachment as a **trusted-operator** boundary, not anonymous wide-area exposure.

**Dispatch path:** Tool handlers call replayt APIs and `pathlib` helpers only. There is **no** `subprocess`, `os.system`, or shell string assembly for MCP arguments.

| Input / surface | Bridge handling | Residual risk |
| --------------- | --------------- | ------------- |
| `target` | Passed to `load_target` | Same as the replayt CLI: **Python import** and **workflow file reads** for resources the server user can access. |
| `inputs_json` (`runner_dry_run_plan`) | Passed to `validation_report` after graph validation | Malformed JSON is reported as `status: "invalid"` via replayt’s validation report (not a bridge-level exception in spot checks). Other unexpected replayt exceptions remain possible and follow the unhandled path below. |
| `store_hint` | `expanduser`, `Path.resolve(strict=False)`, then read-only `JSONLStore` / `SQLiteStore` | Any path the OS allows the process to open; **symlinks** resolve per platform rules. Plain files that are not SQLite are rejected with `_tool_error`. |
| `run_id` | `validate_run_id_for_store` before `load_events` | Identifier validation only; **event payloads** are returned as stored (no bridge redaction). |
| `replayt_echo(message)` | Returned in the structured result | **Reflection** if echoed content is fed into models or UIs; bridge-only tool, still wrapped by `_log_replayt_tool_boundaries` for consistent lifecycle logs (arguments are not logged). |

**Information disclosure:** `_tool_error` returns string `message` fields (from `typer.BadParameter`, `ValueError`, `OSError`, or hint validation). Those strings may include paths or operational detail useful to integrators and visible to **any** connected MCP client—scope who may attach. **Unhandled** exceptions emit a structured `replayt_mcp_bridge.tool.unhandled_exception` line, then `logger.exception` and propagation; presentation to clients depends on FastMCP / host behavior (see [MISSION.md](MISSION.md#security-and-trust-boundaries)).

**Logging:** Tool handlers emit JSON lines with **tool** name, optional **mcp_request_id**, and result **status** at begin/end—**no** client argument values. Sensitive-shaped extra fields are redacted in `observability.py`.

**Follow-ups (product / optional hardening):** Catch a narrow set of unexpected exceptions and return a generic structured error (with correlation id); allowlist `store_hint` roots for multi-tenant deploys; optional event field redaction; stricter documentation staging if integrators want a “milestone 1 only” tool exposure story.

## Related files

| Path | Purpose |
| ---- | ------- |
| `README.md` | Compatibility table and declared replayt line (mirrors `pyproject.toml`) |
| `CHANGELOG.md` | Keep a Changelog history; release notes for integrators |
| `pyproject.toml` | Bridge version and declared `replayt` dependency range (SSoT) |
| `.github/workflows/ci.yml` | Ruff + pytest workflow and replayt floor job |
| `CONTRIBUTING.md` | Local check commands aligned with CI; Releases paragraph |
| `tests/test_version_contract_docs.py` | Contract tests: docs + CI aligned with `pyproject.toml` |
| `docs/SECURITY.md` | Env vars, logging/redaction, deployment, MCP host trust (operator-facing) |
| `src/replayt_mcp_bridge/server.py` | FastMCP app, tool implementations, persistence helpers |
| `src/replayt_mcp_bridge/observability.py` | Structured JSON logging, redaction, log level env |
| `src/replayt_mcp_bridge/__main__.py` | Stdio server entry |
| `docs/MCP_TOOLS.md` | Tool → replayt mapping and input shapes |
| `tests/test_mcp_tools.py` | Contract tests at the replayt boundary |
| `tests/test_security_docs.py` | Doc and policy contract tests (SECURITY.md, README, env read policy) |
| `tests/test_observability.py` | Redaction and structured log emission tests |
