# Positioning — MCP tool bridge for replayt workflow steps

This project **uses** [replayt](https://pypi.org/project/replayt/). It is **not** a fork of replayt. Compatibility,
version pins, and CI are **your** responsibility here.

**Test coverage (required):** ship automated tests for behavior you claim (unit, contract/integration at replayt
boundaries, smoke where useful). Document how to run them in the README and CI.

Pick **one primary** pattern below (you may blend—say which leads):

## 1) Core-gap

_Use when replayt core intentionally omits a capability._

- What is out of core and why?
- What does **this** repo provide instead?
- How do you track replayt releases?

## 2) LLM showcase

_Concrete demo that needs model calls._

- One-sentence use case; which replayt primitives you exercise
- LLM boundaries: secrets, cost, redaction
- What a reviewer runs to verify

## 3) Framework bridge

_Adapter to another framework or runtime._

- Target framework; public API of the bridge
- How **you** maintain consumer-side compatibility (pins, CI matrix)

## 4) Combinator

_Novel composition of replayt + other tools._

- What is stronger together; shared conventions; integration tests where feasible

## Your choice

- **Primary pattern:** **3 — Framework bridge** (MCP as the target framework/runtime for replayt workflow steps).
- **One-paragraph pitch:** This repo exposes replayt-backed workflow steps as MCP tools so editors and agents can invoke
  the same operations through a stable, documented adapter; replayt remains the source of workflow semantics, while
  compatibility, pins, and tests live in this consumer package.
