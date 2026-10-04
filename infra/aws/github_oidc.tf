# GitHub Actions authenticates with short-lived OIDC tokens; no AWS keys are stored in GitHub.

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_arn = (var.create_github_oidc_provider
    ? aws_iam_openid_connect_provider.github[0].arn
  : data.aws_iam_openid_connect_provider.github[0].arn)
}

data "aws_iam_policy_document" "github_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only workflows running on main; pull requests cannot reach the data.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${var.github_sub_prefix}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "pipeline" {
  name                 = "ne-demand-github-actions"
  assume_role_policy   = data.aws_iam_policy_document.github_trust.json
  max_session_duration = 3600
}

# Read and write, but no delete: raw data is append-only.
data "aws_iam_policy_document" "pipeline_data" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }
  statement {
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.data.arn}/*"]
  }
}

resource "aws_iam_role_policy" "pipeline_data" {
  name   = "data-bucket-read-write"
  role   = aws_iam_role.pipeline.id
  policy = data.aws_iam_policy_document.pipeline_data.json
}

# Deploys: push images to the API repository and point the API function at one.
data "aws_iam_policy_document" "pipeline_deploy" {
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # account-wide by AWS design; it only issues a docker login token
  }
  statement {
    actions = [
      "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer", "ecr:DescribeImages", "ecr:ListImages",
    ]
    resources = [aws_ecr_repository.api.arn]
  }
  statement {
    actions = [
      "lambda:UpdateFunctionCode", "lambda:GetFunction", "lambda:GetFunctionConfiguration",
    ]
    resources = ["arn:aws:lambda:${var.region}:${data.aws_caller_identity.current.account_id}:function:ne-demand-api"]
  }
}

resource "aws_iam_role_policy" "pipeline_deploy" {
  name   = "deploy-api"
  role   = aws_iam_role.pipeline.id
  policy = data.aws_iam_policy_document.pipeline_deploy.json
}
