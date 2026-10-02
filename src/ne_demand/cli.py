"""Command-line entry point. Each pipeline stage is added here as a subcommand."""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

import typer

from ne_demand import __version__
from ne_demand.config import Settings
from ne_demand.ingestion import backfill as ingest

app = typer.Typer(no_args_is_help=True, help="New England demand forecasting pipeline.")


@app.callback()
def main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command()
def check_config() -> None:
    """Show resolved settings, with secrets masked."""
    s = Settings()
    typer.echo(f"data root:        {s.ne_data_root}")
    typer.echo(f"mlflow tracking:  {s.mlflow_tracking_uri or './mlruns (local)'}")
    typer.echo(f"ISO-NE account:   {'set' if s.isone_username and s.isone_password else 'MISSING'}")
    typer.echo(f"slack alerts:     {'set' if s.slack_webhook_url else 'not set'}")


@app.command()
def backfill(
    start: Annotated[str, typer.Option(help="First day, YYYY-MM-DD")],
    end: Annotated[str, typer.Option(help="Last day, YYYY-MM-DD")],
    source: Annotated[
        list[str] | None, typer.Option(help="Sources to backfill (default: all)")
    ] = None,
    workers: Annotated[int, typer.Option(help="Parallel requests for ISO-NE sources")] = 4,
) -> None:
    """Backfill raw history. Resumable: existing day partitions are skipped."""
    root = Settings().ne_data_root
    for src in source or ingest.SOURCES:
        n = ingest.backfill(root, src, date.fromisoformat(start), date.fromisoformat(end), workers)
        typer.echo(f"{src}: wrote {n} day partitions under {root}")


@app.command()
def archive() -> None:
    """Snapshot the current ISO load forecast and weather forecast as issued."""
    for path in ingest.archive(Settings().ne_data_root):
        typer.echo(path)
