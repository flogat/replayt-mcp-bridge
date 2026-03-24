"""Typer CLI entrypoint for replayt."""

from __future__ import annotations

import typer

import replayt
from replayt.cli import display as _display
from replayt.cli.commands import register_all
from replayt.cli.config import enforce_min_replayt_version_cli, get_project_config

# Re-export for tests (REPLAY_HTML brace-escaping checks).
REPLAY_HTML_CSS = _display.REPLAY_HTML_CSS
_replay_html = _display.replay_html

app = typer.Typer(no_args_is_help=True, add_completion=False)

_SKIP_MIN_REPLAYT_VERSION = frozenset(
    {"config", "version", "doctor", "init", "init-env-example", "init-gitignore"}
)


@app.callback()
def _replayt_cli_root(ctx: typer.Context) -> None:
    """Enforce optional ``min_replayt_version`` from project config for mutating / workflow commands."""

    if ctx.invoked_subcommand is None:
        return
    if ctx.invoked_subcommand in _SKIP_MIN_REPLAYT_VERSION:
        return
    cfg, _, _, _ = get_project_config()
    enforce_min_replayt_version_cli(cfg, installed=replayt.__version__)


register_all(app)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
