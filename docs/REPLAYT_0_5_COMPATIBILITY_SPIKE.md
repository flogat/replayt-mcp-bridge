# Compatibility spike: replayt `0.5.x` minor line

**Backlog:** Spike compatibility with next replayt minor line (0.5.x)  
**Purpose:** Record findings before widening `replayt>=0.4.25,<0.5`, so integrators are not surprised and CI/docs stay aligned.

## Status summary (executed spike)

| Check | Result |
| ----- | ------ |
| **PyPI artifact** | **No `0.5.x` release** on [pypi.org/project/replayt](https://pypi.org/project/replayt/) as of **2026-03-24**; latest published version observed: **0.4.25** (`pip index versions replayt`). |
| **Full test suite vs 0.5.x wheel/sdist** | **Not run** — no installable `0.5.x` build was available from PyPI. |
| **Declared range in repo** | Unchanged: `replayt>=0.4.25,<0.5` (`pyproject.toml`). |

**Conclusion:** Early spike is **blocked on upstream publication**. When a **pre-release** or **GA** `0.5.x` appears, rerun [§ How to re-run this spike](#how-to-re-run-this-spike) and replace the table above with pass/fail, version pinned, and failure summaries.

## Refined acceptance criteria (for the eventual “widen range” work)

These refine the backlog item for **implementation PRs** after 0.5.x exists:

1. **Recorded findings** — Pass/fail against a named **replayt 0.5.x** (PEP 440 string), noting **wheel vs sdist** if both were tried, and **date** of the run.
2. **Change list** — Bullet list of required **code** or **doc** updates with **rough effort** (`S` small, about an hour; `M` half-day; `L` multi-day) and suggested sequencing.
3. **If widening the declared range** — In one maintainer pass or **split PRs**:
   - `pyproject.toml` dependency line.
   - [README.md](../README.md) **Compatibility with replayt** (exact line + table).
   - [.github/workflows/ci.yml](../.github/workflows/ci.yml) **`replayt-floor`** reinstall pin and job **name** (must match new minimum).
   - [tests/test_version_contract_docs.py](../tests/test_version_contract_docs.py) **`_EXPECTED_REPLAYT_SPEC`** (and any parser assumptions if the spec shape changes).
   - [docs/DESIGN_PRINCIPLES.md](DESIGN_PRINCIPLES.md), [docs/MCP_TOOLS.md](MCP_TOOLS.md) (any prose quoting the range), [docs/ARCHITECTURE.md](ARCHITECTURE.md) version-contract subsection.
   - Optional: refresh [docs/reference-documentation/](reference-documentation/) via `scripts/refresh_replayt_reference_docs.py` if policy is to snapshot the new floor.
   - [CHANGELOG.md](../CHANGELOG.md): **Unreleased** or release note with **migration** text for integrators (see [§ Draft migration note](#draft-migration-note-for-changelog-when-widening)).

## How to re-run this spike

Use a **clean venv** at the repo root.

1. **Discover builds**

   ```bash
   pip index versions replayt
   # or: pip install replayt==0.5.0a1  # example pre-release
   ```

2. **Install the bridge as today, then swap in candidate replayt** (no `pyproject.toml` commit required for the experiment)

   ```bash
   python -m venv .venv-spike
   .venv-spike\Scripts\activate   # Windows
   pip install -U pip
   pip install -e ".[dev]"
   pip install --force-reinstall "replayt>=0.5.0,<0.6" --pre   # adjust spec when versions exist
   ```

   The second line matches CI’s **`replayt-floor`** pattern: editable install first, then **`--force-reinstall`** to the version under test. If pip cannot satisfy the spec, upstream may not have published yet—stop and update § Status summary only.

3. **Run the same checks as CI**

   ```bash
   ruff check src tests
   ruff format --check src tests
   pytest -q
   ```

4. **Update this document** — Replace § Status summary with outcomes, list breaks (import errors, signature changes, CLI parity), and link GitHub issues.

## Bridge ↔ replayt API touchpoints (break analysis)

Code today imports **replayt** from:

| Module / symbol | Used for |
| ---------------- | -------- |
| `replayt.__version__`, `replayt.__version_tuple__` | `replayt_version_info`, package metadata |
| `replayt.cli.config.DEFAULT_LOG_DIR`, `resolve_log_dir` | Persistence defaults |
| `replayt.cli.targets.load_target` | Workflow resolution, `typer.BadParameter` mapping |
| `replayt.cli.validation.validate_workflow_graph`, `validation_report` | `runner_dry_run_plan` |
| `replayt.graph_export.workflow_to_mermaid` | Graph export tool |
| `replayt.persistence.SQLiteStore` | SQLite store reads |
| `replayt.persistence.jsonl.JSONLStore`, `validate_run_id` | JSONL store reads |

Any **removal, rename, or signature change** in these paths is a **high** likelihood of bridge impact. **New required replayt configuration** may surface only at runtime (workflow load, store open).

## Anticipated follow-up work when widening (effort guesses)

Until 0.5.x is exercised, treat these as **planning placeholders**; adjust after the real test run.

| Item | Likelihood | Effort |
| ---- | ---------- | ------ |
| Bump `pyproject.toml` + `_EXPECTED_REPLAYT_SPEC` + README table + CI floor label/pin | Certain if widening | **S** |
| Doc string updates (`MCP_TOOLS`, `MISSION`, `DESIGN_PRINCIPLES`) quoting the range | Certain | **S** |
| Handler fixes for moved/renamed replayt APIs | Depends on upstream | **M–L** |
| New/updated contract tests for changed error types or validation shapes | Depends on upstream | **M** |
| Optional CI job: **`replayt-0.5-ceiling`** or matrix leg on latest `0.5.x` (in addition to floor) | Optional hardening | **M** |

## Draft migration note (for CHANGELOG when widening)

*Paste under **Unreleased** → **Changed** (or the next release section) when support is actually extended. Replace placeholders.*

```markdown
### Changed

- **replayt compatibility** — Supported range widened to `replayt>=A.B.C,<0.6` (see `pyproject.toml`). Integrators on **0.4.x** should pin `replayt-mcp-bridge` to the previous bridge release or upgrade replayt per their own schedules. CI **`replayt-floor`** now reinstalls **`replayt==A.B.C`** to guard the declared minimum.
```
