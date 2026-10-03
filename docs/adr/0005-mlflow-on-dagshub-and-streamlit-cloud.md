# 0005. MLflow on DagsHub, app on Streamlit Community Cloud

Date: 2026-10-03 · Status: accepted (answers two PRD open questions)

## Context

Phase 2 needs a tracking server with a model registry and a public prediction app, within the
$20/month budget and without another always-on server to keep alive.

## Decision

- **MLflow on DagsHub** (free for public repos). Its MLflow UI is public, so anyone can browse
  every run and registry version. Self-hosting on AWS was rejected: $5-12/month and one more
  thing that can go down. Databricks Free Edition was rejected because its UI is private.
- **Registry:** model `ne-demand-lightgbm`. Each training run registers a version and moves the
  `candidate` alias; `production` moves only through `ne-demand promote` (Phase 4's gate will
  call it). Each version carries its lineage as tags: `git_commit`, `data_hash` (content hash
  of the exact training frame), the data window, `run_id`, and on promotion `promotion_reason`
  and `previous_production`.
- The registry replaces the Phase 1 `models/` prefix on S3: the forecast job resolves
  `models:/ne-demand-lightgbm@production`, so there is one source of truth.
- **App on Streamlit Community Cloud**: free, public, redeploys on every push to main. It reads
  `published/forecasts.parquet` and two processed tables with a read-only key scoped to those
  prefixes.

## Consequences

The daily forecast now depends on DagsHub being reachable. An outage fails the run and alerts;
Phase 6 freshness checks will catch a missed day. DagsHub runs its own MLflow server version,
so client features newer than it supports may fail; the code uses only run, tag, and alias APIs.
