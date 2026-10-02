"""Command-line entry point. Each pipeline stage is added here as a subcommand."""

from __future__ import annotations

import typer

from ne_demand import __version__
from ne_demand.config import Settings

app = typer.Typer(no_args_is_help=True, help="New England demand forecasting pipeline.")


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
