# 0007. CI/CD, evaluation gate, and rollback

Date: 2026-10-04 · Status: accepted (answers the PRD's gate-margin question)

## Context

A model should reach production only through an automatic, recorded decision, and a bad
deployment must be reversible in under 5 minutes without a rebuild.

## Decision

**Workflows**
- `ci.yml` (every pull request and push): lint, unit tests, a training smoke test (train,
  register, gate, forecast and serve on synthetic data), and `terraform fmt`/`validate`.
- `deploy.yml` (merge to main touching code or config, or manual): train a candidate, gate it,
  then build the image for whatever is production, push it to ECR, update the Lambda, and
  check that the API serves the expected version. A rejected candidate still redeploys, so code
  changes ship with the current model.
- `rollback.yml` (manual, with a reason): move production back to the version it replaced,
  point the Lambda at that version's existing image, verify, report the time.

**Gate.** Candidate and production are scored on the candidate's holdout window, recomputed on
current data. The candidate never trained on it, and production was trained earlier on older
data, so the days are unseen by both. Each model's features are rebuilt from its own config.
Promote only if candidate MAPE <= production MAPE x (1 - 0.02) **and** candidate MAPE is below
the naive baseline. The 2% relative margin keeps retrains on near-identical data from churning
production.

**Record.** Every registration, decision, promotion and rollback is tagged on the model version
and appended to `published/model_events.parquet`, which the dashboard's model timeline reads.

**Responsibilities.** Terraform owns infrastructure; CI owns which image is live
(`ignore_changes = [image_uri]`). The GitHub role may push to one ECR repository and update one
function.

## Consequences

Verified on the real system (2026-10-04):
- Retrains on the same data (v2, v3) were rejected by the margin.
- A deliberately degraded model (v4, `configs/degraded_demo.yaml`, 17.68% MAPE) was rejected
  automatically for not beating the naive baseline (12.28%):
  [run](https://github.com/vladimir-kazarin/ne-demand-forecast/actions/runs/37167605349).
- Rollback drill v2 -> v1 took 53 s in the job and 69 s from click to a verified API:
  [run](https://github.com/vladimir-kazarin/ne-demand-forecast/actions/runs/37167844527).

Every merge that touches code trains a candidate, so the registry accumulates rejected versions.
That is the record working as intended. Rollback toggles between the current and previous
version; it is not an arbitrary "go to version N" (use `ne-demand promote` plus a deploy).
