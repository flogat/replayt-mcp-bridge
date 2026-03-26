"""Follow-up hints when a run_id lookup returns no events (onboarding / footgun reduction)."""

from __future__ import annotations

from pathlib import Path

import typer

from replayt.cli.config import DEFAULT_LOG_DIR
from replayt.persistence.jsonl import validate_run_id


def exit_on_invalid_run_id(run_id: str) -> str:
    """Echo validation errors to stderr and exit 1 (consistent with ``seal`` / ``report``)."""

    try:
        return validate_run_id(run_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def suggested_runs_list_command(*, cli_log_dir: Path, log_subdir: str | None, sqlite: Path | None) -> str:
    """Argv-shaped string for listing recent runs with the same store resolution as the failing command."""

    parts = ["replayt", "runs", "--limit", "10"]
    if cli_log_dir != DEFAULT_LOG_DIR:
        parts.extend(["--log-dir", str(cli_log_dir)])
    if log_subdir is not None:
        parts.extend(["--log-subdir", log_subdir])
    if sqlite is not None:
        parts.extend(["--sqlite", str(sqlite)])
    return " ".join(parts)


def echo_missing_run_hints(
    *,
    cli_log_dir: Path,
    log_subdir: str | None,
    sqlite: Path | None,
) -> None:
    """Print stderr lines after ``No events for run_id=...``."""

    cmd = suggested_runs_list_command(cli_log_dir=cli_log_dir, log_subdir=log_subdir, sqlite=sqlite)
    typer.echo("Hint: list recent run IDs (first column) with:", err=True)
    typer.echo(f"  {cmd}", err=True)
    typer.echo("After replayt run, the CLI prints run_id=<uuid> in the output.", err=True)
    typer.echo(
        "Hint: if the run should exist, use the same log store as replayt run "
        "(REPLAYT_LOG_DIR, project log_dir, log subdirectory and SQLite options when applicable).",
        err=True,
    )


def echo_empty_runs_hints(
    *,
    store_empty: bool,
    filters_active: bool,
    cli_log_dir: Path,
    log_subdir: str | None,
    sqlite: Path | None,
) -> None:
    """Print stderr lines when ``replayt runs`` text output has no rows."""

    if store_empty:
        typer.echo(
            "Hint: this log store has no run IDs yet. Complete one workflow (for example "
            "`replayt try --example e01_hello_world --live` or `replayt run replayt_examples.e01_hello_world:wf`); "
            "the CLI prints run_id=<uuid> when a run starts.",
            err=True,
        )
        typer.echo("Hint: list packaged examples with `replayt try --list`.", err=True)
    elif filters_active:
        typer.echo(
            "Hint: runs exist in this log store but none matched your filters; "
            "remove or relax flags such as --status, --tag, --run-meta, --tool, --older-than, or --newer-than.",
            err=True,
        )
    else:
        typer.echo(
            "Hint: runs exist but none matched the listing limit or internal filters; "
            "try a larger `--limit` or check `replayt stats` for aggregate counts.",
            err=True,
        )
    typer.echo(
        "Hint: if you expected older runs, use the same log store as the original replayt run "
        "(REPLAYT_LOG_DIR, project log_dir, log subdirectory and SQLite options when applicable).",
        err=True,
    )
    cmd = suggested_runs_list_command(cli_log_dir=cli_log_dir, log_subdir=log_subdir, sqlite=sqlite)
    typer.echo(f"Hint: re-list with the same store flags you use for inspect/replay: `{cmd}`", err=True)
