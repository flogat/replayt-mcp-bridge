"""Tests for ``scripts/run_ci_checks.py`` (fail-fast, cwd, exit codes)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_run_ci_checks():
    path = REPO_ROOT / "scripts" / "run_ci_checks.py"
    spec = importlib.util.spec_from_file_location("_run_ci_checks_under_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_main_fail_fast_returns_first_nonzero_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load_run_ci_checks()
    calls: list[list[str]] = []
    root = mod.repo_root()

    def fake_run(argv, cwd=None, **_kwargs):
        calls.append(list(argv))
        assert cwd == root
        if len(calls) == 1:
            return SimpleNamespace(returncode=7)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod.main() == 7
    assert len(calls) == 1


def test_main_all_steps_zero_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_run_ci_checks()
    calls: list[list[str]] = []
    root = mod.repo_root()

    def fake_run(argv, cwd=None, **_kwargs):
        calls.append(list(argv))
        assert cwd == root
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod.main() == 0
    assert calls == list(mod.CI_CHECK_STEPS)


def test_main_missing_returncode_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_run_ci_checks()

    def fake_run(_argv, _cwd=None, **_kwargs):
        return SimpleNamespace(returncode=None)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod.main() == 1
