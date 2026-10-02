# 0003. Terraform for AWS from v1

Date: 2026-10-02 · Status: accepted (amends 0001, which deferred Terraform)

## Context

The pipeline needs an S3 bucket and an IAM role that GitHub Actions can assume. Creating these
by hand would leave no record of how the environment was built.

## Decision

All AWS resources are defined in `infra/`:

- `infra/bootstrap` creates the Terraform state bucket (local state, applied once).
- `infra/aws` holds the data bucket, the GitHub OIDC provider, the pipeline role, and a
  monthly budget alarm. Its state lives in the bootstrap bucket with S3-native locking.

GitHub Actions authenticates through OIDC, so no AWS keys are stored in GitHub. The role
trusts only workflows on `main` and can read and write the data bucket but not delete, which
makes raw data append-only; bucket versioning recovers accidental overwrites.

## Consequences

Infrastructure is reproducible and reviewable in pull requests. A plan/apply CI workflow is
deferred to Phase 4; until then `terraform apply` is run locally with the `terraform` profile.
