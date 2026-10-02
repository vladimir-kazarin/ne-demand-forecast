# 0002. Data sources and forecast vintages

Date: 2026-10-02 · Status: accepted

## Context

The model must train on weather *as forecast*, and the ISO-NE forecast is only a fair
benchmark if it is the vintage available when our forecast is issued (day-ahead).

Findings from probing the sources on 2026-10-02:

- **ISO-NE load** (5-minute, public ISO Express files via `gridstatus.ISONE`) is available
  historically without an ISO Express login.
- **ISO-NE load forecast** history keeps only the *same-day* vintage (issued ~09:00 ET on the
  day it covers). The current file also includes tomorrow's forecast, issued the day before.
  So the day-ahead vintage cannot be backfilled; it exists only if archived live.
- **Open-Meteo Previous Runs API** returns `temperature_2m_previous_day1/2`: the value
  forecast one or two days before each hour. Coverage was 100% for every month from
  2024-09 to 2026-10 for Boston.

## Decision

- Use the public ISO-NE files for v1; register for ISO Express later for zonal data.
- Backfill weather from the Previous Runs API (`previous_day1` is the training feature).
- Archive the live ISO forecast and Open-Meteo forecast hourly from day one (`ne-demand archive`).
- Report the ISO benchmark in two series: backfilled same-day (advantaged) and archived
  day-ahead (fair), and label them as such on the dashboard.

## Consequences

Until the archive accumulates history, the only ISO benchmark is the same-day vintage, which
has more information than our day-ahead model and should beat it. That gap is expected and is
reported, not hidden.
