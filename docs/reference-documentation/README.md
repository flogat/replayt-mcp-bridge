# Reference documentation (optional offline mirror)

This directory holds **optional** copies of **upstream [replayt](https://pypi.org/project/replayt/)** material so contributors and tooling can read replayt context **without network access** after a one-time refresh.

## Scope

- **In scope:** Replayt’s own user-facing docs shipped with a PyPI release (today: project `README.md` and `LICENSE` from the **source distribution**).
- **Out of scope for this mirror:** Anything that defines **this bridge’s** MCP contracts. Those remain authoritative in this repository under [`docs/MCP_TOOLS.md`](../MCP_TOOLS.md), [`docs/MISSION.md`](../MISSION.md), and related bridge docs. Do not treat snapshots here as the integration contract.

## Layout

| Path | Purpose |
| ---- | ------- |
| [`snapshots/replayt-0.4.25/`](snapshots/replayt-0.4.25/) | Markdown and license text captured from the **replayt 0.4.25** sdist (matches the **declared lower bound** in [`pyproject.toml`](../../pyproject.toml)). |
| (future) | Additional patch snapshots may appear as maintainers refresh the mirror; older trees can stay for diffing. |

Relative links inside mirrored `README.md` (for example to `docs/QUICKSTART.md`) point at paths that exist in replayt’s **full** source tree; they are **not** vendored here unless added in a later refresh. Use the refresh script or PyPI/GitHub for the complete tree.

## Attribution and license

Each snapshot subdirectory includes an **`ATTRIBUTION.md`** file: package version, where the files came from, and license. Upstream replayt is distributed under **Apache License 2.0** (see the mirrored `LICENSE` in the snapshot folder).

## How to refresh

From the repository root (network required):

```bash
python scripts/refresh_replayt_reference_docs.py
```

Optional: pin a version explicitly (must be published on PyPI):

```bash
python scripts/refresh_replayt_reference_docs.py --version 0.4.25
```

After upgrading the declared replayt range in `pyproject.toml`, run the script with a version inside the new range and update this README’s layout table if the snapshot path changes.

## Why this is optional

Nothing in CI or runtime **depends** on these files. They are a convenience for offline agents and humans; the bridge’s supported replayt range and behavior are still defined by **`pyproject.toml`**, tests, and first-party docs under `docs/`.
