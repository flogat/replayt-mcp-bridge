# Dependency audit

CI **`supply-chain`** runs `pip-audit --ignore-vuln CVE-2026-4539 --desc` after `pip install -e ".[dev]"`. PyPA **pip-audit** has no `--severity-high` flag; any reported vulnerability fails unless ignored here and in `.github/workflows/ci.yml`.

## Accepted risk: CVE-2026-4539 (pygments)

Transitive **pygments** (e.g. via **replayt → typer → rich → pygments**) may report **CVE-2026-4539** (ReDoS in **AdlLexer**). We do not use that lexer in bridge code; re-assess when upstream pins move. Remove the ignore from CI when the resolved tree includes a fixed release.
