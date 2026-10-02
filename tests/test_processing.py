import pandas as pd

from ne_demand.processing import iso_forecast, load_hourly, weather_hourly


def _five_min(start: str, periods: int, value: float, fetched: str) -> pd.DataFrame:
    t = pd.date_range(start, periods=periods, freq="5min", tz="America/New_York")
    return pd.DataFrame(
        {"Interval Start": t, "Load": value, "fetched_at": pd.Timestamp(fetched, tz="UTC")}
    )


def test_latest_fetch_wins_and_incomplete_hours_dropped():
    old = _five_min("2026-03-01 00:00", 24, 10_000.0, "2026-03-01 06:00")
    new = _five_min("2026-03-01 00:00", 12, 11_000.0, "2026-03-01 07:00")  # revises hour 0
    hourly = load_hourly(pd.concat([old, new]))
    assert len(hourly) == 2
    assert hourly["load_mw"].tolist() == [11_000.0, 10_000.0]

    partial = load_hourly(_five_min("2026-03-01 00:00", 18, 10_000.0, "2026-03-01 06:00"))
    assert len(partial) == 1  # second hour has only 6 of 12 readings


def test_spring_forward_day_yields_23_hours():
    raw = _five_min("2026-03-08 00:00", 23 * 12, 9_000.0, "2026-03-09 06:00")
    assert len(load_hourly(raw)) == 23


def test_weather_pivots_to_station_columns():
    t = pd.Timestamp("2026-03-01 00:00", tz="UTC")
    raw = pd.DataFrame(
        {
            "time": [t, t],
            "station": ["boston", "hartford"],
            "temperature_2m_previous_day1": [1.0, 2.0],
            "fetched_at": pd.Timestamp("2026-03-02", tz="UTC"),
        }
    )
    wide = weather_hourly(raw)
    assert list(wide.columns) == ["time", "temp_boston", "temp_hartford"]


def test_iso_vintage_labels():
    raw = pd.DataFrame(
        {
            "Interval Start": pd.to_datetime(
                ["2026-03-02 05:00", "2026-03-03 05:00"], utc=True
            ).tz_convert("America/New_York"),
            "Forecast Time": pd.Timestamp("2026-03-02 09:30", tz="America/New_York"),
            "Load Forecast": [12_000, 12_500],
        }
    )
    assert iso_forecast(raw)["vintage"].tolist() == ["same_day", "day_ahead"]
