# New England Electricity Demand Forecasting Pipeline

A live pipeline that forecasts next-day hourly electricity demand for New England and runs
unattended, with every model decision visible on a public dashboard. The operating pipeline is
the product; the forecast is its workload. Forecasts are benchmarked against ISO New England's
own load forecast and a naive same-hour-last-week baseline.

> Status: **Phase 2 done — v1 is live.**
> Production model `ne-demand-lightgbm` v1: 6.5% holdout MAPE vs 12.3% naive.
>
> **[Live forecast app](https://ne-demand-forecast-njvzyctwntwcxquaahetkb.streamlit.app/)** ·
> **[Experiments and model registry (MLflow on DagsHub)](https://dagshub.com/vladimir-kazarin/ne-demand-forecast.mlflow)**

## Pipeline

```
ISO-NE load ─┐
ISO forecast ─┼─> ingest (raw Parquet) ─> validate ─> features ─> train ─> registry ─> gate ─> production
Weather fcst ─┘                                                                 │
                                       batch forecast / API / dashboard <───────┘
                     monitoring (error, drift, freshness) ──> weekly retrain ──> gate
```

## Layout

| Path | Stage |
| --- | --- |
| `src/ne_demand/ingestion/` | Hourly pulls of load, ISO forecast, weather; raw-zone storage |
| `src/ne_demand/processing.py` | Raw partitions to hourly processed tables |
| `src/ne_demand/validation/` | Pandera schemas, run before training and forecasting |
| `src/ne_demand/features/` | Calendar and lag features, one code path for training and serving |
| `src/ne_demand/training/` | Config-driven LightGBM training, MLflow tracking |
| `src/ne_demand/evaluation/` | MAPE and the promotion gate |
| `src/ne_demand/forecast/` | Daily batch forecast and the naive baseline |
| `src/ne_demand/serving/` | FastAPI service |
| `src/ne_demand/monitoring/` | Error, drift, freshness, alerts |
| `dashboard/` | Streamlit prediction app and ops dashboard |
| `configs/` | Training configs |
| `infra/` | Terraform for AWS (state bucket, data bucket, GitHub OIDC role, budget) |
| `docs/adr/` | Decision records |
| `docs/incidents.md` | Incident log |

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
uv sync --all-extras          # or: make install
cp .env.example .env          # add ISO Express credentials
uv run ne-demand check-config
make test

# backfill raw history (resumable) and snapshot today's forecasts
uv run ne-demand backfill --start 2024-09-20 --end 2026-10-01
uv run ne-demand archive

# build processed tables, train, and forecast tomorrow
uv run ne-demand process --start 2024-09-20 --end 2026-10-02
uv run ne-demand train
uv run ne-demand forecast
```

### Infrastructure

```bash
export AWS_PROFILE=terraform
cd infra/bootstrap && terraform init && terraform apply          # once: state bucket
cd ../aws && cp terraform.tfvars.example terraform.tfvars          # set alert_email
terraform init -backend-config="bucket=$(terraform -chdir=../bootstrap output -raw state_bucket)"
terraform apply
```

All timestamps are UTC. Calendar features are computed in `America/New_York` so 23- and 25-hour
daylight-saving days are handled.

## Roadmap

v1 is phases 0–2 (about one week). The full pipeline is about three to four weeks. A phase is done
when its **done-when** check passes.

### Phase 0 — Setup
- [x] Repository, project scaffold, CI
- [x] Confirm the weather API offers archived forecasts for the backfill period ([ADR 0002](docs/adr/0002-data-sources-and-forecast-vintages.md))
- [x] AWS storage and GitHub OIDC role provisioned with Terraform ([ADR 0003](docs/adr/0003-terraform-for-aws.md))
- [x] Register an ISO Express account
- [x] Backfill two years of load, ISO forecast, and forecast weather into raw storage
- [x] Start archiving the ISO forecast and weather forecast as issued
- [x] **Done when:** historical load and weather are in storage

### Phase 1 — Batch forecast with validation
- [x] Hourly ingestion job: idempotent, retries, alerts on failure
- [x] Pandera validation: schema, missing hours, duplicates, value ranges
- [x] Features: lagged load (24 h, 48 h, 168 h), forecast temperature, calendar ([ADR 0004](docs/adr/0004-issue-time-and-features.md))
- [x] LightGBM training from config
- [x] Daily batch forecast of 24 hourly values, stored with model version
- [x] Naive baseline (same hour last week) scored alongside
- [x] **Done when:** a broken column fails the pipeline with a clear error

### Phase 2 — Tracking, registry, first dashboard (**v1 live**)
- [x] MLflow logging of params, metrics, data window, data hash, git commit ([ADR 0005](docs/adr/0005-mlflow-on-dagshub-and-streamlit-cloud.md))
- [x] Model registry with `candidate` and `production` aliases; lineage tags on every version
- [x] Deployed prediction app with the forecast page ([live](https://ne-demand-forecast-njvzyctwntwcxquaahetkb.streamlit.app/); opens without login, matches the stored forecast)
- [ ] App loads in under 3 s (measured 7-10 s on Streamlit Cloud; open)
- [x] **Done when:** the production version traces to its data and commit

### Phase 3 — Serving API
- [ ] FastAPI service with `/health` and `/predict`
- [ ] Docker image, public scale-to-zero deployment
- [ ] Predict form in the app
- [ ] Load test: local p95 under 200 ms
- [ ] **Done when:** a bad model path fails at startup

### Phase 4 — CI/CD, gate, rollback
- [ ] PR workflow: lint, unit tests, training smoke test
- [ ] Merge workflow: build image, register candidate
- [ ] Evaluation gate on a fixed holdout (MAPE, set improvement margin)
- [ ] One-command rollback workflow, logged
- [ ] **Done when:** a degraded model is rejected, and rollback takes under 5 minutes

### Phase 5 — Scheduled retraining
- [ ] Weekly retrain on a rolling window, sent through the gate
- [ ] **Done when:** the log shows promoted and rejected weeks, each with a reason

### Phase 6 — Monitoring and alerts
- [ ] Forecast error tracking (model, ISO, naive)
- [ ] Input drift with Evidently
- [ ] Data freshness and job-failure checks
- [ ] Slack or email alerts
- [ ] **Done when:** an injected input shift fires an alert within one cycle

### Phase 7 — Showcase
- [ ] Architecture diagram
- [ ] Decision records for main tool choices
- [ ] Recorded failure demos: validation failure, rejected model, rollback, drift alert
- [ ] Quickstart and incident log
- [ ] **Done when:** a stranger runs it locally within 60 minutes

### Later iterations
- [ ] All eight New England load zones
- [ ] Day-ahead price forecasting and a paper battery trading simulation
- [ ] Airflow, Kubernetes, and Terraform
- [ ] PyTorch challenger model
