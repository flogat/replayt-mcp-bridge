"""JSONL / SQLite store construction and read helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import typer

from replayt.persistence import JSONLStore, MultiStore, SQLiteStore
from replayt.persistence.jsonl import resolve_jsonl_posix_new_file_mode_from_env


def make_store(log_dir: Path, sqlite: Path | None, *, strict_mirror: bool = False) -> JSONLStore | MultiStore:
    log_dir.mkdir(parents=True, exist_ok=True)
    posix_mode = resolve_jsonl_posix_new_file_mode_from_env()
    primary = JSONLStore(log_dir, posix_new_file_mode=posix_mode)
    if sqlite is None:
        return primary
    sqlite.parent.mkdir(parents=True, exist_ok=True)
    return MultiStore(primary, SQLiteStore(sqlite, posix_new_db_file_mode=posix_mode), strict_mirror=strict_mirror)


def close_store(store: JSONLStore | MultiStore | SQLiteStore) -> None:
    closer = getattr(store, "close", None)
    if callable(closer):
        closer()


@contextmanager
def open_store(
    log_dir: Path,
    sqlite: Path | None,
    *,
    strict_mirror: bool = False,
) -> Iterator[JSONLStore | MultiStore]:
    store = make_store(log_dir, sqlite, strict_mirror=strict_mirror)
    try:
        yield store
    finally:
        close_store(store)


@contextmanager
def read_store(log_dir: Path, sqlite: Path | None) -> Iterator[JSONLStore | SQLiteStore]:
    if sqlite is not None:
        if not sqlite.is_file():
            typer.echo(f"SQLite store not found: {sqlite}", err=True)
            raise typer.Exit(code=1)
        store = SQLiteStore(sqlite, read_only=True)
        try:
            yield store
        finally:
            store.close()
    else:
        yield JSONLStore(log_dir, create=False)
