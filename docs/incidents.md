# Incident log

Short write-ups of real failures in the live pipeline: what broke, how it was detected, impact,
fix, and follow-up.

<!-- ## YYYY-MM-DD — title -->

## 2026-10-03 — GitHub Actions dropped most scheduled runs

**What happened.** On the first full day live, the hourly `Ingest` workflow ran 5 times in
24 hours instead of 24, with gaps up to 6 hours (01:11, 06:31, 12:32, 17:15, 19:57 UTC). The
daily `Daily forecast` cron is set for 14:35 and 15:35 UTC; one run started at 18:07 UTC
(3.5 hours late) and the other never started.

**Impact.** No load or weather data lost: every ingest run re-fetches all of yesterday and
today, and processing keeps the latest value per interval. The live ISO day-ahead archive
captured fewer vintages than planned. Tomorrow's forecast was still issued before midnight.

**Detection.** Manually, by reading `gh run list` while building Phase 2. Nothing alerted:
a run that never starts cannot fail, so failure alerts do not cover it.

**Follow-up.** This is the PRD's top-listed risk. Options: data-freshness alerts (Phase 6),
and moving the trigger off GitHub's cron, e.g. AWS EventBridge Scheduler calling
`workflow_dispatch`, which fires on time.

## 2026-10-04 — Daily forecast never started; caught by the new freshness alert

**What happened.** Neither scheduled run of `Daily forecast` (14:35 and 15:35 UTC) started.
`Ingest` ran 3 times in the first 16 hours of the day.

**Detection.** Automatic, the day monitoring went live: the monitor's `forecast_published`
check fired at 12:19 ET ("no forecast for 2026-10-05 by 12:00 ET") and emailed an alert.

**Impact.** Monday's forecast was issued at 12:20 ET instead of about 10:35 ET, still well
before the day began. No data lost.

**Fix.** Ran the `Daily forecast` workflow manually; it published with production v1, and
the next monitor run sent "RESOLVED: forecast_published".

**Follow-up.** Second scheduler incident in three days. Move the triggers for ingest,
forecast and monitor from GitHub cron to AWS EventBridge Scheduler, which fires on time.
