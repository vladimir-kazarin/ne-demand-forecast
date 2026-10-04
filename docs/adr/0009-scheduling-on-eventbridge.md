# 0009. Schedule jobs from AWS EventBridge Scheduler, run them on GitHub Actions

Date: 2026-10-04 · Status: accepted (supersedes the GitHub-cron part of ADR 0001)

## Context

GitHub Actions cron skipped most hourly ingest runs on day one, and on day three never started
the daily forecast at either scheduled time ([incident log](../incidents.md)). The project's value
is an unbroken 8-week run, and GitHub documents scheduled runs as best effort.

## Decision

- **AWS EventBridge Scheduler** decides when jobs run: ingest hourly at :17 UTC, monitor hourly
  at :47 UTC, and the forecast at **10:32 America/New_York**. Scheduler handles daylight saving,
  replacing the "run at two UTC times and skip one" workaround.
- Each schedule invokes a **dispatcher Lambda** that calls GitHub's `workflow_dispatch` API, which
  starts runs immediately. The jobs still run on GitHub Actions with the same code, secrets and
  logs; only the trigger moved.
- The dispatcher accepts an allow-list of workflows. It reads a **fine-grained GitHub token**
  (Actions read/write on this one repository) from an SSM SecureString at runtime; the token is
  not in code, Terraform state, or GitHub.
- Schedules retry twice within 30 minutes. The **watchdog** (ADR 0008) runs on its own schedule
  and alerts if data, the monitor's heartbeat or the forecast go stale, whatever the cause,
  including an expired token.
- GitHub cron triggers were removed only after a scheduled firing was verified end to end.

## Consequences

- Jobs start within a minute of their scheduled time instead of hours late or never.
- The token expires (at most a year): rotate it with one `aws ssm put-parameter`; the dispatcher
  reads it fresh each run. Until then, an expired token shows up as watchdog alerts.
- One more component (a stdlib Lambda); cost stays within the free tier.
- Running the jobs themselves on AWS (no GitHub runners) is a later option if GitHub becomes the
  bottleneck.
