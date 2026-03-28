# Dependency vulnerability audit (supply-chain CI)

This document is the **policy and audit trail** for CI **dependency vulnerability scanning**. It complements [MISSION.md § CI dependency vulnerability scanning (supply-chain)](MISSION.md#ci-dependency-vulnerability-scanning-supply-chain) and the operator-facing pointer in [SECURITY.md § Dependency vulnerability scanning (CI)](SECURITY.md#dependency-vulnerability-scanning-ci).

**Out of scope here:** **`pip-audit`** does **not** inspect **GitHub Actions** **`uses:`** version pins. Automated bumps for those pins are specified under [MISSION.md § Dependabot (or equivalent) for GitHub Actions pins](MISSION.md#dependabot-or-equivalent-for-github-actions-pins).

## What runs in CI

GitHub Actions job **`supply-chain`** in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) (Linux only, CPython **3.11 / 3.12 / 3.13**):

1. Check out the repo and install **`pip install -e ".[dev]"`** (same editable + dev extras as the main **`test`** job).
2. Run **PyPA [pip-audit](https://pypi.org/project/pip-audit/)** with the **exact** flags below.

**Canonical command** (must stay in sync with the workflow step):

```bash
pip-audit --ignore-vuln CVE-2026-4539 --desc
```

- **`--desc`** — Include short descriptions in logs for triage.
- **`--ignore-vuln`** — Only for CVEs (or equivalent ids) **documented in this file** with maintainer rationale; duplicate the same ids in **`.github/workflows/ci.yml`** so CI and docs cannot drift silently.

## What gets scanned

**pip-audit** inspects the **currently installed** distribution set in the job environment after **`pip install -e ".[dev]"`**. That includes:

- Direct **`[project].dependencies`** (**replayt**, **mcp**, **pytest**) and **everything they pull in** transitively.
- **`[project.optional-dependencies] dev`** (**ruff**, **pip-audit**) and **their** transitive dependencies.

So the scan is **not** “direct requirements only”; it is **the full resolved graph** for that install, which matches how maintainers catch issues on a fresh editable install. It does **not** require a committed lockfile; resolution follows **`pyproject.toml`** ranges and PyPI at job time.

## Tool choice

**Default tool:** **pip-audit** (PyPA), version constrained in **`pyproject.toml`** (`pip-audit>=…` under **`dev`**). Replacing it with another scanner is allowed only if maintainers update **this file**, **`.github/workflows/ci.yml`**, [CONTRIBUTING.md](../CONTRIBUTING.md), and [MISSION.md](MISSION.md) in the **same** change-set so commands and policy stay explicit.

## Severity and gating

**pip-audit** (as used here) does **not** support “fail only above CVSS X” flags. The **project policy** is:

- **Fail** on **any** reported vulnerability **except** those listed under **Accepted risks** below (via **`--ignore-vuln`** in CI **and** prose here).
- To **tighten** behavior later (for example if pip-audit adds severity filters), update **this section** and CI in one PR.

This is **signal**, not **certification**: it does not prove absence of bugs, malicious packages, or vulnerabilities outside the advisory databases pip-audit uses.

### Blocking (CI) vs advisory

- **Blocking:** In GitHub Actions, job **`supply-chain`** runs **`pip-audit`** with normal shell semantics: a **nonzero** exit **fails the job** (and therefore the workflow run for that matrix cell). This is the project’s **enforced** supply-chain gate—not a “warning” channel.
- **Advisory-only automation:** This repository does **not** define a separate CI step that prints vulnerabilities but always exits **0**. If maintainers add one, document it here, in [CONTRIBUTING.md](../CONTRIBUTING.md), and in [MISSION.md](MISSION.md#ci-dependency-vulnerability-scanning-supply-chain) in the **same** change-set so **blocking vs advisory** stays unambiguous.

## Local reproduction

Use the same steps as CI:

```bash
pip install -e ".[dev]"
pip-audit --ignore-vuln CVE-2026-4539 --desc
```

[CONTRIBUTING.md](../CONTRIBUTING.md) lists this alongside Ruff and pytest so PR authors can fail fast before push.

**Network:** **`pip-audit`** consults vulnerability metadata (typically requiring **outbound network** when caches are cold or the tool fetches updates). That is **independent** of **`pytest -q -m "not network"`**: the test suite does **not** invoke **`pip-audit`**, and CI keeps **`supply-chain`** in a **separate** job from **`test`** / **`test-windows`** / **`replayt-floor`** so the default **pytest** bar stays decoupled from the scanner—see [MISSION.md § CI dependency vulnerability scanning (supply-chain)](MISSION.md#ci-dependency-vulnerability-scanning-supply-chain).

## Accepted risks and false positives

When **pip-audit** reports a CVE that is **not actionable** for this repo (e.g. **unreachable code path**, **no fixed release yet**, **ecosystem still resolving**), **do not** silence it only in CI. Add a row below and mirror **`--ignore-vuln`** in **`.github/workflows/ci.yml`**.

**Template for new entries:**

| CVE / id | Package (as reported) | Rationale | Revisit | Tracking |
| -------- | --------------------- | --------- | ------- | -------- |
| `CVE-YYYY-NNNN` | `some-package` | Why the project accepts the risk for this bridge | When to remove ignore (e.g. “after fixed version in tree”) | Link to GitHub issue or internal ticket |

### CVE-2026-4539 (pygments)

| CVE / id | Package (as reported) | Rationale | Revisit | Tracking |
| -------- | --------------------- | --------- | ------- | -------- |
| `CVE-2026-4539` | **pygments** (transitive, e.g. via **replayt → typer → rich → pygments**) | **ReDoS** in **AdlLexer**; bridge and replayt CLI paths used in CI do not exercise that lexer. | Remove **`--ignore-vuln`** when the resolved dependency tree includes a **fixed** pygments release. | _(maintainers: add issue URL when filed)_ |

## Lockfiles

This repository does **not** require a committed **lockfile** for the vulnerability scan. **`pip install -e ".[dev]"`** against **`pyproject.toml`** is the **intentional** model unless maintainers adopt a lockfile workflow in a **dedicated** change-set and document it here and in [CONTRIBUTING.md](../CONTRIBUTING.md).
