# Prediction API: container image in ECR, run on Lambda behind a public Function URL.
# Deploy order on first setup: apply (creates ECR), push an image, then apply with
# -var api_image_tag=<tag> (creates the function). Later deploys only change the tag.

variable "api_image_tag" {
  description = "Image tag in the ne-demand-api repository to run; empty skips the function"
  type        = string
  default     = ""
}

resource "aws_ecr_repository" "api" {
  name = "ne-demand-api"
  # Tags are never reused, so a tag always names the same image (and model version).
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 10 most recent images (enough to roll back)"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
      action       = { type = "expire" }
    }]
  })
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api" {
  name               = "ne-demand-api-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "api_logs" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# The API reads recent demand for lag features; nothing else.
data "aws_iam_policy_document" "api_read" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data.arn}/processed/*"]
  }
}

resource "aws_iam_role_policy" "api_read" {
  name   = "read-processed"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api_read.json
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/ne-demand-api"
  retention_in_days = 14
}

resource "aws_lambda_function" "api" {
  count         = var.api_image_tag == "" ? 0 : 1
  function_name = "ne-demand-api"
  role          = aws_iam_role.api.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
  architectures = ["x86_64"]
  # Lambda CPU scales with memory: 2048 MB (~1.15 vCPU) halves cold-start imports.
  memory_size = 2048
  timeout     = 15

  environment {
    variables = { NE_DATA_ROOT = "s3://${aws_s3_bucket.data.bucket}" }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.api.name
  }

  depends_on = [aws_iam_role_policy_attachment.api_logs]
}

resource "aws_lambda_function_url" "api" {
  count              = length(aws_lambda_function.api)
  function_name      = aws_lambda_function.api[0].function_name
  authorization_type = "NONE"
  cors {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST"]
    allow_headers = ["content-type"]
  }
}

# No explicit aws_lambda_permission: with authorization_type NONE the provider adds both
# statements a public URL needs (InvokeFunctionUrl, and InvokeFunction limited to calls
# via the URL). Declaring them again duplicates them and races the provider's own update.

output "api_ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "api_url" {
  value = one(aws_lambda_function_url.api[*].function_url)
}
