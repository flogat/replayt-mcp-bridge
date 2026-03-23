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
variables and logging/redaction expectations for integrators (see also **LLM / demos** below).

**Inputs:** Validate and normalize tool arguments at this bridge’s boundary; avoid passing untrusted strings into shells,
dynamic code execution, or paths outside documented intent.

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

## Audience

| Audience | Needs |
| -------- | ----- |
| **Maintainers** | This mission, scripts, pinned versions, release notes |
| **Integrators** | Stable adapter surface, compatibility expectations |
| **Contributors** | README, tests, coding expectations |
