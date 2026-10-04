# 0006. Prediction API on AWS Lambda, model baked into the image

Date: 2026-10-03 · Status: accepted

## Context

Phase 3 needs a public prediction API on a scale-to-zero host within the $20/month budget,
with a startup check that refuses a bad model.

## Decision

- **FastAPI in one Docker image** that runs both locally and on **AWS Lambda**. The AWS Lambda
  Web Adapter (1.1.0) forwards invocations to uvicorn, so the app has no Lambda-specific code.
  A public **Function URL** fronts it; no API Gateway.
- **The model is exported into the image at build time** (`ne-demand export-model`). One image
  serves exactly one registry version, the image tag names both (`<commit>-v<version>`), tags are
  immutable, and ECR keeps the last 10. Rolling back means pointing Lambda at an earlier tag.
  Serving does not depend on DagsHub being reachable.
- **Startup validation:** a missing or corrupt bundle, or features that don't match the
  metadata, raise during startup, so the service never starts with a bad model.
- **One feature path:** `/predict` calls the same `build_features` as the batch forecast, with
  lagged demand from `processed/load_hourly` as known at the day's scheduled issue time. A test
  checks that the API and the batch job return the same value for the same inputs.
- **Least privilege:** the function's role can only read `processed/`.
- AWS Lambda over Cloud Run: same account, Terraform and OIDC setup; no second cloud.

## Consequences

Measured: local p95 105 ms (500 requests, concurrency 10); over the internet p95 72 ms at
concurrency 4. Cold start is about 3-4 s (the first call after a deploy, which also pulls the
image, took up to 10 s).

Found while deploying:
- A 9 s adapter readiness timeout failed every cold start; it was removed.
- Bytecode was not precompiled, and Lambda's read-only filesystem recompiled everything on each
  cold start. Precompiling cut imports from 4.1 s to 1.8 s at Lambda-like CPU; 2048 MB memory
  (more CPU) cut them to 1.0 s.
- The history cache keyed its first refresh on `monotonic()`, which is near zero on a fresh
  micro-VM, so new instances served without lag features for 10 minutes. Fixed with a
  regression test.
- Declaring Function URL permissions alongside the provider's own raced and returned 409.

The account allows 10 concurrent executions, which caps invocations near 100/s per function:
bursts beyond that get 429s. That doubles as a cost cap on the public endpoint, but heavy use
could crowd out other Lambdas in the account. Deploying is manual until Phase 4 (build, push,
`terraform apply -var api_image_tag=...`).
