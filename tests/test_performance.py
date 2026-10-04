from datetime import date, timedelta

import numpy as np
import pandas as pd

from ne_demand.features.build import target_hours
from ne_demand.monitoring.performance import check_performance, rolling, score_days

DAYS = [date(2026, 3, 1) + timedelta(days=i) for i in range(10)]
rng = np.random.default_rng(1)


def _actual() -> pd.DataFrame:
    idx = target_hours(DAYS[0])
    for d in DAYS[1:]:
        idx = idx.append(target_hours(d))
    return pd.DataFrame({"time": idx, "load_mw": 12_000 + rng.normal(0, 300, len(idx))})


def _forecasts(load: pd.DataFrame, model_err: float, naive_err: float) -> pd.DataFrame:
    rows = []
    for d in DAYS:
        hours = target_hours(d)
        act = load.set_index("time")["load_mw"].reindex(hours)
        rows.append(
            pd.DataFrame(
                {
                    "time": hours,
                    "forecast_mw": act * (1 + model_err),
                    "naive_mw": act * (1 + naive_err),
                    "model_version": "ne-demand-lightgbm/v1",
                    "target_day": d,
                    "issued_at": hours[0] - pd.Timedelta(hours=14),
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def _iso(load: pd.DataFrame) -> pd.DataFrame:
    t = load["time"]
    return pd.concat(
        [
            pd.DataFrame(
                {
                    "time": t,
                    "forecast_time": t - pd.Timedelta(hours=20),
                    "iso_forecast_mw": load["load_mw"] * 1.03,
                    "vintage": "day_ahead",
                }
            ),
            pd.DataFrame(
                {
                    "time": t,
                    "forecast_time": t - pd.Timedelta(hours=2),
                    "iso_forecast_mw": load["load_mw"] * 1.01,
                    "vintage": "same_day",
                }
            ),
        ],
        ignore_index=True,
    )


def test_scores_each_finished_day_against_benchmarks():
    load = _actual()
    errors = score_days(_forecasts(load, 0.05, 0.12), load, _iso(load))
    assert len(errors) == 10
    row = errors.iloc[0]
    assert round(row.model_mape, 6) == 5.0 and round(row.naive_mape, 6) == 12.0
    assert round(row.iso_same_day_mape, 6) == 1.0
    assert row.on_time


def test_iso_day_ahead_uses_only_vintages_issued_before_our_forecast():
    load = _actual()
    iso = _iso(load)
    iso.loc[iso.vintage == "day_ahead", "forecast_time"] += pd.Timedelta(
        hours=10
    )  # issued after us
    errors = score_days(_forecasts(load, 0.05, 0.12), load, iso)
    assert errors["iso_day_ahead_mape"].isna().all()


def test_unfinished_day_is_not_scored():
    load = _actual()
    partial = load.iloc[:-5]  # last day missing its final hours
    assert len(score_days(_forecasts(load, 0.05, 0.12), partial, _iso(load))) == 9


def test_healthy_week_raises_no_alert():
    load = _actual()
    errors = score_days(_forecasts(load, 0.05, 0.12), load, _iso(load))
    assert check_performance(errors, holdout_mape=6.5) == []
    assert round(rolling(errors, 7)["model_mape"], 6) == 5.0


def test_model_worse_than_naive_alerts():
    load = _actual()
    errors = score_days(_forecasts(load, 0.15, 0.12), load, _iso(load))
    alerts = check_performance(errors, holdout_mape=6.5)
    assert any("naive" in a for a in alerts)
    assert any("twice" in a for a in alerts)


def test_too_few_days_never_alert():
    load = _actual()
    errors = score_days(_forecasts(load, 0.5, 0.12), load, _iso(load)).head(3)
    assert check_performance(errors, holdout_mape=6.5) == []
