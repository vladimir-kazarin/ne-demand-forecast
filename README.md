# New England Electricity Demand Forecasting Pipeline

A live pipeline that forecasts next-day hourly electricity demand for New England and runs
unattended, with every model decision visible on a public dashboard. The operating pipeline is
the product; the forecast is its workload. Forecasts are benchmarked against ISO New England's
own load forecast and a naive same-hour-last-week baseline.

> Status: **Milestone 0 — setup.** Live dashboard link and architecture diagram land in milestone 2.

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
| `src/ne_demand/validation/` | Pandera schemas, run before training and forecasting |
| `src/ne_demand/features/` | Calendar and lag features, one code path for training and serving |
| `src/ne_demand/training/` | Config-driven LightGBM training, MLflow tracking |
| `src/ne_demand/evaluation/` | MAPE and the promotion gate |
| `src/ne_demand/forecast/` | Daily batch forecast and the naive baseline |
| `src/ne_demand/serving/` | FastAPI service |
| `src/ne_demand/monitoring/` | Error, drift, freshness, alerts |
| `dashboard/` | Streamlit prediction app and ops dashboard |
| `configs/` | Training configs |
| `docs/adr/` | Decision records |
| `docs/incidents.md` | Incident log |

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
uv sync --all-extras          # or: make install
cp .env.example .env          # add ISO Express credentials
uv run ne-demand check-config
make test
```

All timestamps are UTC. Calendar features are computed in `America/New_York` so 23- and 25-hour
daylight-saving days are handled.

## Milestones

| # | Scope | Status |
| --- | --- | --- |
| 0 | ISO Express account, repository, two-year backfill | in progress |
| 1 | Ingestion, validation, features, LightGBM, daily forecast, naive baseline | |
| 2 | MLflow tracking and registry, deployed prediction app — **v1 live** | |
| 3 | FastAPI service, Docker, public deployment, load test | |
| 4 | CI/CD, evaluation gate, rollback | |
| 5 | Weekly retraining through the gate | |
| 6 | Monitoring and alerts | |
| 7 | Architecture diagram, decision records, failure demos, quickstart | |
