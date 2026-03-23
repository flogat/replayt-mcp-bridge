#!/usr/bin/env python3
"""Download replayt sdist from PyPI and refresh docs/reference-documentation/snapshots/."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_version_from_pyproject(root: Path) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'"replayt>=([\d.]+),', text)
    if not m:
        msg = "Could not parse replayt lower bound from pyproject.toml"
        raise SystemExit(msg)
    return m.group(1)


def pypi_sdist_url(version: str) -> str:
    url = f"https://pypi.org/pypi/replayt/{version}/json"
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 — PyPI only
        data = json.load(resp)
    urls = data.get("urls") or []
    for item in urls:
        if item.get("packagetype") == "sdist" and item.get("url"):
            return str(item["url"])
    msg = f"No sdist URL found for replayt=={version}"
    raise SystemExit(msg)


def extract_readme_license(archive_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as tf:
        members = {m.name: m for m in tf.getmembers() if m.isfile()}
        prefix = None
        for name in members:
            if name.endswith("/README.md"):
                prefix = name[: -len("README.md")]
                break
        if prefix is None:
            msg = "Could not find README.md in sdist"
            raise SystemExit(msg)
        for rel in ("README.md", "LICENSE"):
            key = f"{prefix}{rel}"
            if key not in members:
                msg = f"Missing {rel} in sdist"
                raise SystemExit(msg)
            src = tf.extractfile(members[key])
            if src is None:
                msg = f"Could not read {rel} from sdist"
                raise SystemExit(msg)
            (dest / rel).write_bytes(src.read())


def write_attribution(dest: Path, version: str) -> None:
    body = f"""# Snapshot attribution — replayt {version}

| Field | Value |
| ----- | ----- |
| **Upstream package** | `replayt` on PyPI |
| **Version** | `{version}` |
| **Source** | Source distribution from [replayt {version} on PyPI](https://pypi.org/project/replayt/{version}/#files) |
| **Files mirrored here** | `README.md`, `LICENSE` (as shipped in that sdist) |
| **SPDX license** | `Apache-2.0` (see `LICENSE` in this directory) |

This mirror is maintained by **replayt-mcp-bridge** contributors for offline reference only; it is **not** an official replayt release artifact.
"""
    (dest / "ATTRIBUTION.md").write_text(body, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        help="replayt version to fetch (default: lower bound from pyproject.toml)",
    )
    args = parser.parse_args()
    root = repo_root()
    version = args.version or default_version_from_pyproject(root)
    pkg_url = pypi_sdist_url(version)

    dest = (
        root / "docs" / "reference-documentation" / "snapshots" / f"replayt-{version}"
    )

    with tempfile.TemporaryDirectory() as tmp:
        tgz = Path(tmp) / f"replayt-{version}.tar.gz"
        try:
            urllib.request.urlretrieve(pkg_url, tgz)  # noqa: S310
        except urllib.error.URLError as e:
            print(f"Download failed: {e}", file=sys.stderr)
            raise SystemExit(1) from e
        extract_readme_license(tgz, dest)
    write_attribution(dest, version)
    print(f"Updated {dest.relative_to(root)}")


if __name__ == "__main__":
    main()
