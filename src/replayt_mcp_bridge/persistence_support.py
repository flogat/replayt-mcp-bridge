"""Persistence path resolution and read-only store helpers for MCP tools."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from replayt.cli.config import DEFAULT_LOG_DIR, resolve_log_dir
from replayt.persistence import SQLiteStore
from replayt.persistence.jsonl import JSONLStore

from replayt_mcp_bridge.observability import parse_default_run_event_field_allowlist


def _path_allowed_under_store_hint_roots(path: Path, roots: list[Path]) -> bool:
    return any(path.is_relative_to(root) for root in roots)


def _effective_run_event_field_allowlist(
    event_fields: list[str] | None,
) -> list[str] | None:
    """Resolve top-level key allowlist: explicit non-empty MCP list wins; else optional env default."""

    if event_fields is not None:
        if not event_fields:
            return None
        return event_fields
    return parse_default_run_event_field_allowlist()


def _filter_run_events_top_level_keys(events: list[Any], keys: list[str]) -> list[Any]:
    """Keep only listed top-level keys on dict-shaped events; other elements pass through unchanged."""

    seen: set[str] = set()
    ordered: list[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            ordered.append(k)
    out: list[Any] = []
    for ev in events:
        if isinstance(ev, dict):
            out.append({k: ev[k] for k in ordered if k in ev})
        else:
            out.append(ev)
    return out


def _split_typed_store_hint(store_hint: str) -> tuple[str | None, str]:
    """Split ``store_hint`` into an optional explicit kind and filesystem path string.

    Recognized forms (ASCII, case-insensitive on the keyword):

    * ``jsonl-dir:`` / ``jsonl:`` → kind ``jsonl`` (JSONL log directory only).
    * ``sqlite:`` → kind ``sqlite``.
    * ``file:`` when **not** followed by ``//`` → kind ``file`` (same suffix heuristics as a legacy bare path;
      excludes RFC 8089 ``file://…`` URIs, which stay legacy opaque strings).
    * Anything else → ``(None, trimmed_string)`` (legacy bare path).

    The path part is trimmed of leading whitespace and passed through ``expanduser`` / ``resolve`` like legacy hints.
    """

    s = store_hint.strip()
    lower = s.lower()
    # ``jsonl:`` is a prefix of ``jsonl-dir:`` — match the longer keyword first.
    if lower.startswith("jsonl-dir:"):
        return "jsonl", s[10:].lstrip()
    if lower.startswith("jsonl:"):
        return "jsonl", s[6:].lstrip()
    if lower.startswith("sqlite:"):
        return "sqlite", s[7:].lstrip()
    if lower.startswith("file:") and not lower.startswith("file://"):
        return "file", s[5:].lstrip()
    return None, s


def _resolve_persistence_paths(
    store_hint: str | None,
) -> tuple[Path | None, Path | None, str | None]:
    """Return ``(log_dir, sqlite_path, error)`` for JSONL (directory) or SQLite file backends."""

    if store_hint is None:
        return resolve_log_dir(DEFAULT_LOG_DIR), None, None
    explicit_kind, path_str = _split_typed_store_hint(store_hint)
    if explicit_kind is not None and not path_str:
        return (
            None,
            None,
            "store_hint uses a typed prefix (file:, jsonl-dir:, jsonl:, or sqlite:) but the path part is empty; "
            "see docs/MCP_TOOLS.md (store_hint grammar).",
        )
    raw = Path(path_str).expanduser()
    try:
        p = raw.resolve(strict=False)
    except (OSError, RuntimeError):
        p = raw
    if explicit_kind == "sqlite":
        return None, p, None
    if explicit_kind == "jsonl":
        if p.exists() and p.is_file():
            return (
                None,
                None,
                "Typed JSONL-directory store_hint (jsonl: or jsonl-dir:) must refer to a JSONL log directory, "
                "not a file.",
            )
        return p, None, None

    suf = p.suffix.lower()
    if suf in (".sqlite", ".db"):
        return None, p, None
    if p.exists() and p.is_file():
        return (
            None,
            None,
            f"Store hint {store_hint!r} is a plain file; pass a JSONL log directory or a .sqlite/.db path.",
        )
    return p, None, None


@contextmanager
def _open_read_store(
    log_dir: Path | None, sqlite: Path | None
) -> Iterator[JSONLStore | SQLiteStore]:
    if sqlite is not None:
        st = SQLiteStore(sqlite, read_only=True)
        try:
            yield st
        finally:
            st.close()
    else:
        assert log_dir is not None
        yield JSONLStore(log_dir, create=False)
