# 0001. v1 stack

Date: 2026-10-02 · Status: accepted

## Context

Solo portfolio project, ≤ $20/month running cost, must run unattended for 8+ weeks and be
reproducible locally within 60 minutes.

## Decision

Parquet on S3 for storage, GitHub Actions for scheduling and CI/CD, Pandera for validation,
LightGBM as the first model, MLflow for tracking and registry, FastAPI in Docker on a
scale-to-zero host for serving, Evidently for drift, Streamlit for the dashboard.
Python 3.12 managed with uv.

## Consequences

Low cost and little to operate. GitHub scheduled workflows can run late and are disabled after
60 days without repository activity, so data-freshness alerting is required (milestone 6).
Airflow, Kubernetes and Terraform are deferred to later iterations.

Still open: MLflow hosting, dashboard/API hosting, forecast issue time, gate margin.
