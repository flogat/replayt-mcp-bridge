# Design principles

Revise as the project matures. Defaults below are minimal—expand with rules for **your** codebase.

1. **Explicit contracts** — Document supported replayt (and third-party framework) versions; test integration boundaries.
2. **Small public surfaces** — Prefer narrow APIs and documented extension points.
3. **Observable automation** — Local scripts and CI produce clear logs and exit codes.
4. **Consumer-side maintenance** — Compatibility shims and pins live **here**; upstream changes are tracked with tests
   and changelog notes.
5. **Not a lever on core** — This repo does not exist to steer replayt core; propose upstream changes through normal
   channels.

## replayt version contract

**Declared range** — `[project].dependencies` in `pyproject.toml` lists the supported **replayt** versions (currently
`>=0.4.25,<0.5`). That is the contract `pip install -e .` and downstream installs resolve against.

**Range vs pin** — This package uses a **narrow PEP 440 range**, not a single `==` pin: patch releases from upstream
should install without a bridge release; the **upper bound** excludes the next pre-1.0 minor line until maintainers
confirm compatibility and widen it. **Integrators** may still pin an exact replayt version in their own lockfiles or
constraints for reproducible deploys.

**Tracking upstream** — When replayt publishes releases outside the declared range, update `pyproject.toml`, this
section, and any CI matrix that exercises the boundary; note the change in the changelog when behavior or required
APIs shift.

## LLM / demos (if applicable)

Document models, secrets handling, cost and redaction expectations here or in MISSION.

## Audience (extend)

| Audience | Needs |
| -------- | ----- |
| **Maintainers** | Mission, scripts, pinned versions, release notes |
| **Integrators** | Stable adapter surface, compatibility matrix |
| **Contributors** | README, tests, coding expectations |
