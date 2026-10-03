"""Public prediction app: tomorrow's forecast and past days against actual demand.

Reads three tables the pipeline publishes; no pipeline code is imported, so the
app installs in seconds on Streamlit Community Cloud.

    published/forecasts.parquet   every issued forecast, with model version
    processed/load_hourly.parquet actual hourly demand
    processed/iso_forecast.parquet ISO-NE forecasts with vintage labels

Locally: NE_DATA_ROOT=data uv run --extra dashboard streamlit run dashboard/app.py
"""

from __future__ import annotations

import os

import fsspec
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

LOCAL_TZ = "America/New_York"
REPO_URL = "https://github.com/vladimir-kazarin/ne-demand-forecast"
STALE_AFTER = pd.Timedelta(hours=24)

# Reference palette, categorical slots 1-3, validated light and dark (dataviz validator).
# Actual demand is the reference line, drawn in primary ink rather than a series hue.
PALETTE = {
    "light": {
        "actual": "#0b0b0b",
        "model": "#2a78d6",
        "iso": "#eb6834",
        "naive": "#1baf7a",
        "grid": "#e6e5e0",
        "muted": "#52514e",
        "label_bg": "rgba(255,255,255,0.85)",
    },
    "dark": {
        "actual": "#ffffff",
        "model": "#3987e5",
        "iso": "#d95926",
        "naive": "#199e70",
        "grid": "#383835",
        "muted": "#c3c2b7",
        "label_bg": "rgba(14,17,23,0.85)",
    },
}

st.set_page_config(page_title="New England Demand Forecast", page_icon="⚡", layout="wide")


# ---------- data ----------


def _secret(key: str, default=None):
    try:
        return st.secrets.get(key, default)
    except FileNotFoundError:
        return default
    except Exception:  # no secrets file outside Streamlit Cloud
        return default


def _root() -> str:
    return _secret("NE_DATA_ROOT") or os.environ.get("NE_DATA_ROOT", "data")


def _storage_options() -> dict:
    aws = _secret("aws")
    return {"key": aws["access_key_id"], "secret": aws["secret_access_key"]} if aws else {}


@st.cache_data(ttl=600, show_spinner=False)
def read_table(rel: str) -> pd.DataFrame:
    path = f"{_root().rstrip('/')}/{rel}"
    try:
        with fsspec.open(path, "rb", **_storage_options()) as f:
            return pd.read_parquet(f)
    except FileNotFoundError:
        return pd.DataFrame()


def local_wall_time(ts: pd.Series | pd.DatetimeIndex):
    """UTC -> New England wall-clock time without tz, so charts show local hours."""
    return pd.DatetimeIndex(ts).tz_convert(LOCAL_TZ).tz_localize(None)


def day_forecast(forecasts: pd.DataFrame, day) -> pd.DataFrame:
    """Latest issued forecast for a target day."""
    rows = forecasts[forecasts["target_day"] == day]
    return rows[rows["issued_at"] == rows["issued_at"].max()].set_index("time").sort_index()


def day_iso(iso: pd.DataFrame, idx: pd.DatetimeIndex, issued_at) -> tuple[pd.Series, str]:
    """Fair ISO comparison: the day-ahead vintage available when our forecast was issued.
    Falls back to the same-day vintage, labelled as such (ADR 0002)."""
    rows = iso[iso["time"].isin(idx)]
    fair = rows[(rows["vintage"] == "day_ahead") & (rows["forecast_time"] <= issued_at)]
    label = "ISO-NE day-ahead"
    if fair.empty:
        fair, label = rows[rows["vintage"] == "same_day"], "ISO-NE same-day"
    latest = fair.sort_values("forecast_time").drop_duplicates("time", keep="last")
    return latest.set_index("time")["iso_forecast_mw"].reindex(idx), label


def mape(actual: pd.Series, pred: pd.Series) -> float | None:
    ok = actual.notna() & pred.notna()
    return float(((actual[ok] - pred[ok]).abs() / actual[ok]).mean() * 100) if ok.any() else None


# ---------- chart ----------


def chart(series: list[tuple[str, str, pd.Series, str]], colors: dict) -> go.Figure:
    """series: (label, color key, values indexed by UTC time, dash). One y-axis, MW."""
    fig = go.Figure()
    plotted = [(lbl, k, v, d) for lbl, k, v, d in series if not v.dropna().empty]
    for label, key, values, dash in plotted:
        fig.add_trace(
            go.Scatter(
                x=local_wall_time(values.index),
                y=values.to_numpy(),
                name=label,
                mode="lines",
                line={"color": colors[key], "width": 2, "dash": dash},
                hovertemplate="%{y:,.0f} MW",
            )
        )
    # Direct labels at line ends, so identity is never color alone. Ends that land close
    # together are pushed apart by a minimum gap so the labels never overlap.
    ends = sorted(((v.dropna().iloc[-1], v.dropna().index[-1], lbl) for lbl, _, v, _ in plotted))
    all_y = pd.concat([v for _, _, v, _ in plotted]).dropna()
    gap = (all_y.max() - all_y.min()) * 0.06
    placed: list[float] = []
    # Labels sit in blank space right of the data (no side margin, so phones keep the width).
    x_all = local_wall_time(all_y.index)
    x_end = x_all.max() + pd.Timedelta(hours=4)
    for y, _, label in ends:
        y_label = max(y, placed[-1] + gap) if placed else y
        placed.append(y_label)
        fig.add_annotation(
            x=x_end,
            y=y_label,
            text=label,
            showarrow=False,
            xanchor="right",
            xshift=-4,
            bgcolor=colors["label_bg"],
            font={"color": colors["muted"], "size": 12},
        )
    fig.update_layout(
        hovermode="x unified",
        margin={"l": 8, "r": 8, "t": 64, "b": 8},
        height=420,
        legend={
            "orientation": "h",
            "x": 0,
            "y": 1.02,
            "yanchor": "bottom",
            "font": {"color": colors["muted"]},
        },
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": colors["muted"]},
    )
    # autorange would widen the axis to fit the label text; pin it to the data instead.
    fig.update_xaxes(
        range=[x_all.min(), x_end],
        autorange=False,
        showgrid=False,
        tickformat="%-I %p",
        showspikes=True,
        spikemode="across",
        spikethickness=1,
        spikecolor=colors["grid"],
        spikedash="solid",
    )
    fig.update_yaxes(gridcolor=colors["grid"], ticksuffix=" MW", tickformat=",.0f", zeroline=False)
    return fig


def table(series: list[tuple[str, str, pd.Series, str]]) -> pd.DataFrame:
    cols = {label: values.round(0) for label, _, values, _ in series if not values.dropna().empty}
    df = pd.DataFrame(cols)
    df.index = local_wall_time(df.index).strftime("%-I %p")
    df.index.name = "Hour (ET)"
    return df


# ---------- page ----------

theme = getattr(getattr(st.context, "theme", None), "type", None) or "light"
colors = PALETTE["dark" if theme == "dark" else "light"]

forecasts = read_table("published/forecasts.parquet")
load = read_table("processed/load_hourly.parquet")
iso = read_table("processed/iso_forecast.parquet")

st.title("New England electricity demand forecast")
st.markdown(
    "A live pipeline forecasts tomorrow's hourly electricity demand for the ISO New England "
    "grid every morning at 10:30 ET, and scores it against ISO-NE's own forecast and a naive "
    f"same-hour-last-week baseline. [Source and decision records]({REPO_URL})"
)

if forecasts.empty:
    st.error("No forecasts published yet.")
    st.stop()

now = pd.Timestamp.now(tz="UTC")
latest_issue = forecasts["issued_at"].max()
if now - latest_issue > STALE_AFTER:
    st.warning(
        f"⚠️ Stale data: the latest forecast was issued "
        f"{(now - latest_issue).total_seconds() / 3600:.0f} hours ago. The pipeline may be down."
    )

# --- Tomorrow ---
next_day = forecasts["target_day"].max()
f = day_forecast(forecasts, next_day)
issued_at = f["issued_at"].iloc[0]
peak_time = f["forecast_mw"].idxmax()

st.subheader(f"Forecast for {pd.Timestamp(next_day):%A, %B %-d}")
c1, c2, c3 = st.columns(3)
c1.metric(
    "Peak demand",
    f"{f['forecast_mw'].max():,.0f} MW",
    help=f"at {local_wall_time([peak_time])[0]:%-I %p} ET",
)
# "ne-demand-lightgbm/v1" shows as "v1"; forecasts issued before the registry existed
# ("pre-registry/<model id>") show as "pre-registry", with the id in the tooltip.
name, _, ver = f["model_version"].iloc[0].rpartition("/")
shown = name if name == "pre-registry" else ver
c2.metric(
    "Model version",
    shown,
    help=f"{f['model_version'].iloc[0]}, commit {f['git_commit'].iloc[0][:7]}",
)
c3.metric("Issued", f"{issued_at.tz_convert(LOCAL_TZ):%b %-d, %-I:%M %p} ET")

iso_next, iso_label = (
    day_iso(iso, f.index, issued_at) if not iso.empty else (pd.Series(dtype=float), "")
)
next_series = [
    ("Model forecast", "model", f["forecast_mw"], "solid"),
    (iso_label, "iso", iso_next, "solid"),
    ("Naive (last week)", "naive", f["naive_mw"], "dash"),
]
st.plotly_chart(
    chart(next_series, colors), use_container_width=True, config={"displayModeBar": False}
)
with st.expander("Table"):
    st.dataframe(table(next_series), use_container_width=True)

# --- Past days ---
st.subheader("How did past forecasts do?")
today_local = now.tz_convert(LOCAL_TZ).date()
actual = load.set_index("time")["load_mw"] if not load.empty else pd.Series(dtype=float)
done_days = sorted(d for d in forecasts["target_day"].unique() if d < today_local)

if not done_days:
    st.info(
        "Comparisons appear once the first forecast day has finished. "
        f"The first live forecast covers {min(forecasts['target_day']):%B %-d}."
    )
else:
    day = st.date_input("Day", value=done_days[-1], min_value=done_days[0], max_value=done_days[-1])
    if day not in done_days:
        st.info("No forecast was issued for that day.")
    else:
        pf = day_forecast(forecasts, day)
        act = actual.reindex(pf.index)
        iso_day, iso_day_label = day_iso(iso, pf.index, pf["issued_at"].iloc[0])
        m1, m2, m3 = st.columns(3)
        for col, label, pred in [
            (m1, "Model MAPE", pf["forecast_mw"]),
            (m2, f"{iso_day_label} MAPE", iso_day),
            (m3, "Naive MAPE", pf["naive_mw"]),
        ]:
            v = mape(act, pred)
            col.metric(label, f"{v:.1f}%" if v is not None else "n/a")
        past_series = [
            ("Actual", "actual", act, "solid"),
            ("Model forecast", "model", pf["forecast_mw"], "solid"),
            (iso_day_label, "iso", iso_day, "solid"),
            ("Naive (last week)", "naive", pf["naive_mw"], "dash"),
        ]
        st.plotly_chart(
            chart(past_series, colors), use_container_width=True, config={"displayModeBar": False}
        )
        with st.expander("Table"):
            st.dataframe(table(past_series), use_container_width=True)

st.caption(
    "ISO-NE day-ahead is the vintage available when our forecast was issued, archived live since "
    "Oct 2, 2026. Where it is missing, the same-day vintage is shown; it has more information "
    "than a day-ahead model and is labelled as such. Times are Eastern."
)
