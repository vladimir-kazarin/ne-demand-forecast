# 0004. Forecast issue time and feature timing

Date: 2026-10-02 · Status: accepted (answers a PRD open question)

## Context

A next-day forecast is only honest if every feature was known when it was issued. The PRD
left the issue time open.

## Decision

- **Issue time:** 10:30 America/New_York on the day before the target day, configurable as
  `issue_time_local`. It mirrors a day-ahead market timeline and leaves margin for the ~2-minute
  ISO-NE data delay. GitHub cron runs at 14:35 and 15:35 UTC; `ne-demand forecast --scheduled`
  keeps the first run at or after 10:30 local.
- **Known data:** an hour starting at `t` is usable only if `t + 1h <= issue_time`.
- **Lags:** 24 h, 48 h, and 168 h. The 24 h lag is known only for target hours before 10:00
  and is NaN otherwise, in training and serving alike; 48 h and 168 h are always known.
  `last_known_load` and `lead_hours` give the model the most recent level and horizon.
- **Training simulates issuance:** `training_frame` builds each historical day through the same
  `build_features` call as serving, using that day's scheduled issue time. A unit test checks
  every lag value in the training frame against its day's cutoff.
- **Weather:** training uses Open-Meteo `temperature_2m_previous_day1` (lead ≈ 24 h); serving
  uses the forecast fetched at issue time (lead 14-38 h). The vintages are close but not
  identical, a known, small train/serve gap.

## Consequences

The first model (v1, holdout Sep 4 - Oct 1 2026) scored 6.53% MAPE against 12.07% for the
naive baseline and 1.12% for the ISO same-day forecast. Lag and weather-vintage choices are
the first places to look for accuracy gains.
