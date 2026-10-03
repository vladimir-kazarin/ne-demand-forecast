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
