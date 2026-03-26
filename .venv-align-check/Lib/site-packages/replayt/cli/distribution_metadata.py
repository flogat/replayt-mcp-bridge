"""Installed-distribution metadata for platform and CI probes."""

from __future__ import annotations

DISTRIBUTION_METADATA_SCHEMA = "replayt.distribution_metadata.v1"


def _optional_metadata_str(value: object | None) -> str | None:
    """Return stripped metadata text, or ``None`` if missing, empty, or not a string."""

    if value is None or not isinstance(value, str):
        return None
    s = value.strip()
    return s or None


def _sorted_project_urls(meta: object) -> list[dict[str, str]]:
    """Parse PEP 566 ``Project-URL`` headers into stable ``label`` / ``url`` pairs."""

    getter = getattr(meta, "get_all", None)
    if getter is None:
        return []
    try:
        raw_list = getter("Project-URL", [])
    except (TypeError, ValueError):
        return []
    if not isinstance(raw_list, (list, tuple)):
        return []
    if not raw_list:
        return []
    out: list[dict[str, str]] = []
    for raw in raw_list:
        if not raw or not isinstance(raw, str):
            continue
        label, _sep, rest = raw.partition(",")
        url = rest.strip()
        lab = label.strip()
        if lab and url:
            out.append({"label": lab, "url": url})
    out.sort(key=lambda row: (row["label"].lower(), row["url"]))
    return out


def build_distribution_metadata_report() -> dict[str, object]:
    """Return wheel / PyPI metadata for the ``replayt`` distribution when installed.

    When the package is importable from a source tree without an installed
    distribution record (``PYTHONPATH=src``), ``ok`` is false and version fields
    are null so callers can branch without guessing.
    """

    from importlib.metadata import PackageNotFoundError, metadata

    try:
        meta = metadata("replayt")
    except PackageNotFoundError:
        return {
            "schema": DISTRIBUTION_METADATA_SCHEMA,
            "ok": False,
            "detail": "distribution 'replayt' not found in importlib.metadata",
            "version": None,
            "requires_python": None,
            "summary": None,
            "license": None,
            "project_urls": None,
        }

    return {
        "schema": DISTRIBUTION_METADATA_SCHEMA,
        "ok": True,
        "detail": "metadata from installed replayt distribution",
        "version": _optional_metadata_str(meta.get("Version")),
        "requires_python": _optional_metadata_str(meta.get("Requires-Python")),
        "summary": _optional_metadata_str(meta.get("Summary")),
        "license": _optional_metadata_str(meta.get("License")),
        "project_urls": _sorted_project_urls(meta),
    }
