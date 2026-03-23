"""Ensure the declared replayt dependency resolves and matches the supported range."""

from __future__ import annotations

import importlib.metadata


def test_replayt_installable_and_version_in_range() -> None:
    ver = importlib.metadata.version("replayt")
    parts = tuple(int(p) for p in ver.split(".")[:3])
    assert parts >= (0, 4, 25), f"replayt {ver} below supported floor (see pyproject.toml / DESIGN_PRINCIPLES)"
    assert parts < (0, 5, 0), f"replayt {ver} outside supported upper bound (see pyproject.toml / DESIGN_PRINCIPLES)"

    import replayt  # noqa: F401 — dependency must be importable, not only listed

    assert hasattr(replayt, "__version__")
