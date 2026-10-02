import numpy as np
import pandas as pd

from ne_demand.features.calendar import calendar_features
from ne_demand.features.lags import lag_features


def _hourly(start: str, periods: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=periods, freq="h", tz="UTC")


def test_spring_forward_day_has_23_local_hours():
    # 2026-03-08 is the US spring-forward day; local midnight is 05:00 UTC.
    idx = _hourly("2026-03-08 05:00", 23)
    hours = calendar_features(idx)["hour"].tolist()
    assert len(hours) == 23
    assert 2 not in hours


def test_fall_back_day_repeats_1am():
    # 2026-11-01 is the fall-back day; local midnight is 04:00 UTC.
    idx = _hourly("2026-11-01 04:00", 25)
    hours = calendar_features(idx)["hour"].tolist()
    assert hours.count(1) == 2


def test_holiday_flag_uses_local_date():
    # Christmas 2026 is a Friday. 04:00 UTC is still Dec 24 locally (EST, UTC-5).
    idx = pd.DatetimeIndex(["2026-12-25 04:00", "2026-12-25 06:00"], tz="UTC")
    assert calendar_features(idx)["is_holiday"].tolist() == [False, True]


def test_lags_never_use_data_after_issue_time():
    load = pd.Series(np.arange(24 * 14, dtype=float), index=_hourly("2026-01-01", 24 * 14))
    issue_time = pd.Timestamp("2026-01-10 12:00", tz="UTC")
    target = _hourly("2026-01-11 00:00", 24)
    feats = lag_features(load, target, [24, 168], issue_time)

    for lag in (24, 168):
        source_end = target - pd.Timedelta(hours=lag) + pd.Timedelta(hours=1)
        col = feats[f"load_lag_{lag}h"]
        assert col[source_end > issue_time].isna().all()
        assert col[source_end <= issue_time].notna().all()


def test_target_hours_follow_local_days():
    from datetime import date

    from ne_demand.features.build import target_hours

    assert len(target_hours(date(2026, 3, 8))) == 23
    assert len(target_hours(date(2026, 11, 1))) == 25
    assert len(target_hours(date(2026, 6, 1))) == 24


def test_training_frame_uses_only_data_known_at_each_days_issue_time(tables):
    from datetime import date, time, timedelta

    from ne_demand.features.build import scheduled_issue_time, training_frame

    load_df, weather_df = tables
    load = load_df.set_index("time")["load_mw"]
    temps = weather_df.set_index("time")
    days = [date(2026, 3, 1) + timedelta(days=i) for i in range(10)]
    frame = training_frame(load, temps, days, time(10, 30), [24, 48, 168])

    for day, rows in frame.groupby("target_day"):
        issue = scheduled_issue_time(day, time(10, 30))
        known = load[load.index + pd.Timedelta(hours=1) <= issue]
        assert (rows["last_known_load"] == known.iloc[-1]).all()
        for lag in (24, 48, 168):
            src = rows.index - pd.Timedelta(hours=lag)
            leaked = (src + pd.Timedelta(hours=1) > issue) & rows[f"load_lag_{lag}h"].notna()
            assert not leaked.any(), f"lag {lag}h leaks data after issue on {day}"
