# 0008. Monitoring: error first, calibrated drift checks, a watchdog outside GitHub

Date: 2026-10-04 · Status: accepted

## Context

The project's value depends on an unbroken 8-week run, and on day one GitHub's scheduler
skipped most hourly jobs ([incident log](../incidents.md)). The PRD asks for error, drift,
freshness and job-failure monitoring with alerts, and that an injected input shift fires an
alert within one monitoring cycle.

## Decision

**Forecast error is the primary alarm.** Actual demand arrives the next day, so every finished
day is scored against actuals, next to naive, ISO day-ahead (vintage issued no later than ours)
and ISO same-day (labelled). Alert after 5+ scored days if the 7-day error is no better than
naive, or more than twice the production model's holdout error.

**Drift checks were calibrated on a year of real weeks before being trusted.** A backtest over
49 weeks (Oct 2025 - Oct 2026), each week against the same weeks one year earlier:

| Check | Weeks alerting |
| --- | --- |
| Raw-feature PSI >= 0.25 (the textbook rule) | 49 of 49 |
| Station consistency (a station's offset from the regional mean moves >= 2.5 °C) | 1 |
| Out of range (> 2% of hours beyond the training range ± 2 °C) | 2 |
| Either of the two above | 2 (4%), both in the Jan/Feb 2026 Arctic outbreak |

One week of hourly weather is effectively seven samples, and this year's weather is not last
year's, so raw PSI measures weather, not a problem. It is kept as dashboard context. The two
alerting checks target what breaks this model: data faults (wrong station, unit change, stale
feed) and extrapolation beyond the training range. An injected +3 °C error on one station fires.

**Tools.** The drift statistics are a small tested module (PSI, KS, station offsets, range).
Evidently 0.6 renders a browsable HTML report per day. Evidently 0.7 needs `plotly<6` while the
ISO-NE client needs `plotly~=6`; upgrade when that clears.

**Alerts** go by email through AWS SNS (Terraform). Each check alerts once when it starts
failing, reminds every 24 hours, and sends a resolved message.

**A watchdog outside GitHub.** A small Lambda (standard library + boto3) runs hourly on
EventBridge Scheduler and checks S3 timestamps: demand data, the monitor's heartbeat, and
today's forecast. It catches jobs that never start, including the monitor itself.

## Consequences

- Drift that is "just weather" does not page anyone; error tracking catches a model that
  handles weather badly.
- The thresholds rest on one year of history; revisit after the first winter live.
- Monitoring runs hourly on GitHub, and the watchdog covers its gaps from inside AWS.
