"""Forecast error tracking: the primary alarm, since actual demand arrives daily.

For every finished day with a published forecast, score the forecast that was in
place before the day began against actual demand, next to the benchmarks:

- naive: same hour last week (stored with each forecast)
- ISO day-ahead: the latest ISO vintage issued no later than our forecast (fair)
- ISO same-day: issued on the day itself (advantaged; reported, labelled)

    {root}/published/forecast_errors.parquet   one row per scored day
"""

from __future__ import annotations

import fsspec
import pandas as pd

from ne_demand.features.build import target_hours
from ne_demand.processing import read_processed

ERRORS = "published/forecast_errors.parquet"
MIN_DAYS_FOR_ALERT = 5


def _mape(actual: pd.Series, pred: pd.Series) -> float | None:
    ok = actual.notna() & pred.notna()
    if not ok.any():
        return None
    return float(((actual[ok] - pred[ok]).abs() / actual[ok]).mean() * 100)


def _read(root: str, rel: str) -> pd.DataFrame:
    fs, path = fsspec.core.url_to_fs(f"{root.rstrip('/')}/{rel}")
    if not fs.exists(path):
        return pd.DataFrame()
    with fs.open(path, "rb") as f:
        return pd.read_parquet(f)


def read_errors(root: str) -> pd.DataFrame:
    return _read(root, ERRORS)


def _latest_vintage(rows: pd.DataFrame, hours: pd.DatetimeIndex) -> pd.Series:
    """The most recently issued ISO value for each hour."""
    latest = rows.sort_values("forecast_time").drop_duplicates("time", keep="last")
    return latest.set_index("time")["iso_forecast_mw"].reindex(hours)


def score_days(forecasts: pd.DataFrame, load: pd.DataFrame, iso: pd.DataFrame) -> pd.DataFrame:
    """One row per finished day: MAPE of the model and each benchmark."""
    actual = load.set_index("time")["load_mw"]
    rows = []
    for day, f in forecasts.groupby("target_day"):
        hours = target_hours(day)
        if not hours.isin(actual.index).all():
            continue  # day not finished, or actuals missing
        on_time = f[f["issued_at"] < hours[0]]
        f = on_time if not on_time.empty else f  # prefer the forecast in place before the day
        f = f[f["issued_at"] == f["issued_at"].max()].set_index("time").reindex(hours)
        issued_at = f["issued_at"].dropna().iloc[0]
        act = actual.reindex(hours)

        day_iso = iso[iso["time"].isin(hours)] if not iso.empty else iso

        iso_da = iso_sd = None
        if not day_iso.empty:
            da = day_iso[
                (day_iso["vintage"] == "day_ahead") & (day_iso["forecast_time"] <= issued_at)
            ]
            iso_da = _mape(act, _latest_vintage(da, hours)) if not da.empty else None
            sd = day_iso[day_iso["vintage"] == "same_day"]
            iso_sd = _mape(act, _latest_vintage(sd, hours)) if not sd.empty else None
        rows.append(
            {
                "target_day": day,
                "model_version": f["model_version"].dropna().iloc[0],
                "issued_at": issued_at,
                "on_time": bool(issued_at < hours[0]),
                "hours": len(hours),
                "model_mape": _mape(act, f["forecast_mw"]),
                "naive_mape": _mape(act, f["naive_mw"]),
                "iso_day_ahead_mape": iso_da,
                "iso_same_day_mape": iso_sd,
            }
        )
    return pd.DataFrame(rows)


def update_errors(root: str) -> pd.DataFrame:
    """Score every finished day and rewrite the errors table (idempotent)."""
    forecasts = _read(root, "published/forecasts.parquet")
    if forecasts.empty:
        return pd.DataFrame()
    scored = score_days(
        forecasts, read_processed(root, "load_hourly"), read_processed(root, "iso_forecast")
    )
    if scored.empty:
        return scored
    fs, path = fsspec.core.url_to_fs(f"{root.rstrip('/')}/{ERRORS}")
    fs.makedirs(path.rsplit("/", 1)[0], exist_ok=True)
    with fs.open(path, "wb") as f:
        scored.to_parquet(f, index=False)
    return scored


def rolling(errors: pd.DataFrame, days: int) -> dict[str, float | None]:
    """Mean daily MAPE over the most recent `days` scored days, per forecast."""
    recent = errors.sort_values("target_day").tail(days)
    cols = ["model_mape", "naive_mape", "iso_day_ahead_mape", "iso_same_day_mape"]
    return {c: (float(recent[c].mean()) if recent[c].notna().any() else None) for c in cols}


def check_performance(errors: pd.DataFrame, holdout_mape: float | None) -> list[str]:
    """Alerts when the last week's forecasts are clearly worse than they should be."""
    if len(errors) < MIN_DAYS_FOR_ALERT:
        return []
    week = rolling(errors, 7)
    model, naive = week["model_mape"], week["naive_mape"]
    alerts = []
    if model is not None and naive is not None and model >= naive:
        alerts.append(
            f"7-day forecast error {model:.1f}% is no better than the naive baseline ({naive:.1f}%)"
        )
    if model is not None and holdout_mape and model > 2 * holdout_mape:
        alerts.append(
            f"7-day forecast error {model:.1f}% is more than twice the production model's "
            f"holdout error ({holdout_mape:.1f}%)"
        )
    return alerts
