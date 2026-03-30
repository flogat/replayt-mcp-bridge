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

**