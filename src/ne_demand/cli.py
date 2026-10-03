"""Command-line entry point. Each pipeline stage is a subcommand."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import typer

from ne_demand import __version__
from ne_demand.config import LOCAL_TZ, Settings, load_train_config
from ne_demand.ingestion import backfill as ingest

app = typer.Typer(no_args_is_help=True, help="New England demand forecasting pipeline.")


@app.callback()
def main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def alerting(fn: Callable) -> Callable:
    """Alert on any failure of a scheduled job, then exit non-zero."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            from ne_demand.monitoring.alerts import send_alert

            send_alert(
                f"`ne-demand {fn.__name__.removesuffix('_cmd')}` failed: {type(e).__name__}: {e}"
            )
            raise typer.Exit(1) from e

    return wrapper


def _today_local() -> date:
    import pandas as pd

    return pd.Timestamp.now(tz=LOCAL_TZ).date()


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
@alerting
def archive() -> None:
    """Snapshot the current ISO load forecast and weather forecast as issued."""
    for path in ingest.archive(Settings().ne_data_root):
        typer.echo(path)


@app.command(name="ingest")
@alerting
def ingest_cmd() -> None:
    """Hourly job: pull recent load and live forecasts, then update processed tables."""
    from ne_demand.processing import process

    root = Settings().ne_data_root
    for path in ingest.ingest_recent(root):
        typer.echo(path)
    today = _today_local()
    process(root, today - timedelta(days=1), today)


@app.command(name="process")
@alerting
def process_cmd(
    start: Annotated[
        str | None, typer.Option(help="First raw partition day (default: yesterday)")
    ] = None,
    end: Annotated[str | None, typer.Option(help="Last raw partition day (default: today)")] = None,
) -> None:
    """Rebuild processed hourly tables from raw partitions in a date range."""
    from ne_demand.processing import process

    today = _today_local()
    s = date.fromisoformat(start) if start else today - timedelta(days=1)
    e = date.fromisoformat(end) if end else today
    typer.echo(process(Settings().ne_data_root, s, e))


@app.command(name="train")
@alerting
def train_cmd(
    config: Annotated[str, typer.Option(help="Training config YAML")] = "configs/lightgbm_v1.yaml",
) -> None:
    """Train a model from a config, score the holdout, and save a new model version."""
    from ne_demand.training.train import train

    meta = train(load_train_config(config), Settings().ne_data_root)
    typer.echo(f"model: {meta['version']}  registry: v{meta['registry_version']}")
    for k, v in meta["metrics"].items():
        typer.echo(f"  {k}: {v:.2f}%")


@app.command(name="forecast")
@alerting
def forecast_cmd(
    day: Annotated[str | None, typer.Option(help="Target day (default: tomorrow, local)")] = None,
    scheduled: Annotated[
        bool,
        typer.Option(help="Skip unless past the issue time and tomorrow has no forecast yet"),
    ] = False,
) -> None:
    """Issue the next-day hourly forecast with the latest model."""
    import pandas as pd

    from ne_demand.forecast.batch import forecast_exists, run_forecast

    root = Settings().ne_data_root
    now = datetime.now(UTC)
    if scheduled:
        local = pd.Timestamp(now).tz_convert(LOCAL_TZ)
        issue_at = load_train_config("configs/lightgbm_v1.yaml").issue_time_local
        tomorrow = local.date() + timedelta(days=1)
        if local.time() < issue_at:
            typer.echo(f"skip: {local:%H:%M} local is before the {issue_at:%H:%M} issue time")
            return
        if forecast_exists(root, tomorrow):
            typer.echo(f"skip: forecast for {tomorrow} already published")
            return
    out = run_forecast(root, date.fromisoformat(day) if day else None, now)
    typer.echo(out[["time", "forecast_mw", "naive_mw"]].to_string(index=False))


@app.command()
def promote(
    version: Annotated[str, typer.Argument(help="Registry version to put in production")],
    reason: Annotated[str, typer.Option(help="Why; recorded on the model version")],
) -> None:
    """Point the production alias at a registry version (Phase 4 automates this via the gate)."""
    from ne_demand.training.tracking import promote as do_promote

    do_promote(version, reason)
    typer.echo(f"production -> v{version}")
