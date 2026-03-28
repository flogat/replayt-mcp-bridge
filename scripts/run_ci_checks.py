#!/usr/bin/env python3
"""Run the same Ruff and pytest invocations as CI test jobs (fail-fast).

Assumes the environment already has the package installed with dev extras
(``pip install -e ".[dev]"``), matching CI install steps. Exits with the failing
subprocess return code when a step fails; otherwise 0.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Kept in lockstep with .github/workflows/ci.yml — ``test``, ``test-windows``,
# and ``replayt-floor`` lint + test steps (contract-tested).
CI_CHECK_STEPS: tuple[list[str], ...] = (
    ["ruff", "check", "src", "tests"],
    ["ruff", "format", "--check", "src", "tests"],
    ["pytest", "-q", "-m", "not network"],
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> int:
    root = repo_root()
    os.chdir(root)
    for argv in CI_CHECK_STEPS:
        completed = subprocess.run(argv, cwd=root)
        code = completed.returncode
        if code is None:
            return 1
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
