"""Operations: is the pipeline healthy, how accurate is it, what changed, and why.

Everything here is read from files the pipeline publishes under published/.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from common import LOCAL_TZ, REPO_URL, read_bytes, read_json, read_table
from common import colors as theme_colors

colors = theme_colors()
SPREAD_ALERT_C = 2.5
OUT_OF_RANGE_ALERT = 0.02
CHECK_LABELS = {
    "data_freshness": "Demand data is fresh",
    "forecast_published": "Tomorrow's forecast published",
    "forecast_error": "Forecast error within bounds",
    "input_drift": "Inputs consistent and in range",
    "watchdog_data_freshness": "Watchdog: demand data fresh",
    "watchdog_monitor_heartbeat": "Watchdog: monitor is running",
    "watchdog_forecast_published": "Watchdog: forecast written today",
}
EVENT_LABELS = {
    "registered": "📦 registered",
    "promoted": "🚀 promoted",
    "rejected": "⛔ rejected",
    "rolled_back": "⏪ rolled back",
}

st.title("Operations")
st.markdown(
    "How the pipeline is running: health checks, forecast accuracy, every model decision, "
    f"and input drift. [How monitoring works]({REPO_URL}#roadmap-decisions-and-tradeoffs)"
)

now = pd.Timestamp.now(tz="UTC")


def date_span(days: pd.Series) -> list:
    """Date axis range of at least two weeks, so a lone point is not zoomed to milliseconds."""
    d = pd.to_datetime(days)
    return [min(d.min(), d.max() - pd.Timedelta(days=13)), d.max() + pd.Timedelta(days=1)]


def ago(ts) -> str:
    if ts is None or pd.isna(ts):
        return "never"
    minutes = (now - pd.Timestamp(ts)).total_seconds() / 60
    return f"{minutes:.0f} min ago" if minutes < 120 else f"{minutes / 60:.1f} h ago"


# --- Health ---
st.subheader("Health")
status = read_json("published/monitoring/status.json")
watchdog = read_json("published/monitoring/watchdog_state.json")
rows = []
for key, result in (status.get("checks") or {}).items():
    rows.append(
        {
            "Check": CHECK_LABELS.get(key, key),
            "Status": "✅ ok" if result == "ok" else "🔴 failing",
            "Detail": "" if result == "ok" else result,
        }
    )
for key, state in watchdog.items():
    firing = state.get("firing", False)
    rows.append(
        {
            "Check": CHECK_LABELS.get(key, key),
            "Status": "🔴 failing" if firing else "✅ ok",
            "Detail": f"since {state.get('since', '')}" if firing else "",
        }
    )
load = read_table("processed/load_hourly.parquet")
forecasts = read_table("published/forecasts.parquet")
h1, h2, h3 = st.columns(3)
h1.metric("Monitor last ran", ago(status.get("checked_at")))
h2.metric(
    "Latest demand data",
    ago(load["time"].max() + pd.Timedelta(hours=1)) if not load.empty else "none",
)
h3.metric(
    "Latest forecast issued", ago(forecasts["issued_at"].max()) if not forecasts.empty else "none"
)
if rows:
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
else:
    st.info("No monitoring results yet.")

# --- Accuracy ---
st.subheader("Forecast accuracy")
errors = read_table("published/forecast_errors.parquet")
if errors.empty:
    st.info(
        "Scores appear once the first forecast day has finished and the hourly monitor has run "
        "(shortly after midnight ET)."
    )
else:
    errors = errors.sort_values("target_day")

    def window(n: int, col: str) -> str:
        v = errors.tail(n)[col].mean()
        return "n/a" if pd.isna(v) else f"{v:.1f}%"

    cols = st.columns(3)
    for col, (label, field) in zip(
        cols,
        [
            ("Model", "model_mape"),
            ("ISO-NE day-ahead", "iso_day_ahead_mape"),
            ("Naive (last week)", "naive_mape"),
        ],
        strict=True,
    ):
        col.metric(f"{label}, 7-day MAPE", window(7, field), help=f"30-day: {window(30, field)}")
    fig = go.Figure()
    for label, field, key, dash in [
        ("Model", "model_mape", "model", "solid"),
        ("ISO-NE day-ahead", "iso_day_ahead_mape", "iso", "solid"),
        ("Naive (last week)", "naive_mape", "naive", "dash"),
    ]:
        s = errors.set_index("target_day")[field].dropna()
        if s.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=s.index,
                y=s.values,
                name=label,
                mode="lines+markers",
                line={"color": colors[key], "width": 2, "dash": dash},
                marker={"size": 8},
                hovertemplate="%{y:.1f}%",
            )
        )
    fig.update_layout(
        height=320,
        margin={"l": 8, "r": 8, "t": 40, "b": 8},
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.02, "yanchor": "bottom", "x": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": colors["muted"]},
    )
    fig.update_yaxes(title="Daily MAPE (%)", gridcolor=colors["grid"], rangemode="tozero")
    fig.update_xaxes(showgrid=False, tickformat="%b %-d", range=date_span(errors["target_day"]))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with st.expander("Table"):
        st.dataframe(errors.round(2), hide_index=True, use_container_width=True)

# --- Model timeline ---
st.subheader("Model timeline")
events = read_table("published/model_events.parquet")
if events.empty:
    st.info("No model events yet.")
else:
    ev = events.sort_values("at", ascending=False).copy()
    ev["When (ET)"] = (
        pd.to_datetime(ev["at"], utc=True).dt.tz_convert(LOCAL_TZ).dt.strftime("%b %-d, %-I:%M %p")
    )
    ev["Event"] = ev["event"].map(EVENT_LABELS).fillna(ev["event"])
    ev["Version"] = "v" + ev["version"].astype(str)
    st.dataframe(
        ev[["When (ET)", "Event", "Version", "reason"]].rename(columns={"reason": "Reason"}),
        hide_index=True,
        use_container_width=True,
    )

# --- Drift ---
st.subheader("Input drift")
st.markdown(
    "Alerts fire on drift that breaks this model: a station's temperature moving away from the "
    f"others by {SPREAD_ALERT_C} °C or more (a data fault), or more than {OUT_OF_RANGE_ALERT:.0%} "
    "of hours outside the training range (extrapolation). Different weather from last year is "
    "the model's job, so it is shown below as context only."
)
history = read_table("published/monitoring/drift_history.parquet")
if history.empty:
    st.info("No drift checks yet.")
else:
    history = history.sort_values("checked_at")
    real, drills = history[~history["drill"]], history[history["drill"]]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=real["day"],
            y=real["max_spread_shift_c"],
            name="Largest station shift",
            mode="lines+markers",
            line={"color": colors["model"], "width": 2},
            marker={"size": 8},
            customdata=real["max_spread_station"],
            hovertemplate="%{y:.2f} °C (%{customdata})",
        )
    )
    if not drills.empty:
        fig.add_trace(
            go.Scatter(
                x=drills["day"],
                y=drills["max_spread_shift_c"],
                name="Drill (injected)",
                mode="markers",
                marker={"size": 11, "symbol": "x", "color": colors["iso"]},
                hovertemplate="drill: %{y:.2f} °C",
            )
        )
    fig.add_hline(
        y=SPREAD_ALERT_C,
        line={"color": colors["muted"], "width": 1, "dash": "dash"},
        annotation_text=f"alert at {SPREAD_ALERT_C} °C",
        annotation_position="top left",
        annotation_font_color=colors["muted"],
    )
    fig.update_layout(
        height=300,
        margin={"l": 8, "r": 8, "t": 40, "b": 8},
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.02, "yanchor": "bottom", "x": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": colors["muted"]},
    )
    fig.update_yaxes(
        title="°C vs same weeks last year", gridcolor=colors["grid"], rangemode="tozero"
    )
    fig.update_xaxes(showgrid=False, tickformat="%b %-d", range=date_span(history["day"]))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    latest = real.iloc[-1] if not real.empty else None
    if latest is not None:
        d1, d2 = st.columns(2)
        d1.metric(
            "Hours outside training range (latest week)",
            f"{latest['out_of_range_share']:.0%}",
            help=f"Alert above {OUT_OF_RANGE_ALERT:.0%}",
        )
        d2.metric(
            "Drift alert", "🔴 yes" if latest["alerts"] else "✅ none", help=latest["alerts"] or ""
        )

    context = read_table("published/monitoring/drift_latest.parquet")
    with st.expander("Context: per-feature PSI vs the same weeks last year (not alerting)"):
        st.caption(
            "PSI above 0.25 is the classic 'shifted' rule of thumb. On one week of hourly "
            "weather it fires almost every week (49 of 49 in a backtest), because this week's "
            "weather is simply not last year's. That is why it is shown here and does not alert."
        )
        if not context.empty:
            st.dataframe(
                context[
                    ["feature", "psi", "psi_status", "ks_stat", "reference_mean", "current_mean"]
                ].round(3),
                hide_index=True,
                use_container_width=True,
            )
    if latest is not None:
        report = read_bytes(f"published/monitoring/reports/drift_{latest['day']}.html")
        if report:
            st.download_button(
                "Download the Evidently drift report (HTML)",
                report,
                file_name=f"drift_{latest['day']}.html",
                mime="text/html",
            )
