# Alerting and the freshness watchdog.
#
# Alerts: one SNS topic, emailed to var.alert_email (confirm the subscription email once).
# Watchdog: a small Lambda run hourly by EventBridge Scheduler, inside AWS, so stalled
# GitHub schedules are still noticed (see watchdog/handler.py and docs/incidents.md).

variable "watchdog_schedule_enabled" {
  description = "Run the watchdog hourly (needs scheduler permissions on the deployer role)"
  type        = bool
  default     = true
}

resource "aws_sns_topic" "alerts" {
  name = "ne-demand-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# GitHub Actions (monitor and job-failure alerts) may publish to the topic.
data "aws_iam_policy_document" "pipeline_alerts" {
  statement {
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }
}

resource "aws_iam_role_policy" "pipeline_alerts" {
  name   = "publish-alerts"
  role   = aws_iam_role.pipeline.id
  policy = data.aws_iam_policy_document.pipeline_alerts.json
}

# --- watchdog Lambda ---

data "archive_file" "watchdog" {
  type        = "zip"
  source_file = "${path.module}/watchdog/handler.py"
  output_path = "${path.module}/.build/watchdog.zip"
}

resource "aws_iam_role" "watchdog" {
  name               = "ne-demand-watchdog"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "watchdog_logs" {
  role       = aws_iam_role.watchdog.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "watchdog" {
  statement {
    sid     = "ReadTimestamps"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.data.arn}/processed/load_hourly.parquet",
      "${aws_s3_bucket.data.arn}/published/forecasts.parquet",
      "${aws_s3_bucket.data.arn}/published/monitoring/status.json",
      "${aws_s3_bucket.data.arn}/published/monitoring/watchdog_state.json",
    ]
  }
  statement {
    sid       = "KeepAlertState"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.data.arn}/published/monitoring/watchdog_state.json"]
  }
  statement {
    sid       = "Alert"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }
}

resource "aws_iam_role_policy" "watchdog" {
  name   = "watchdog"
  role   = aws_iam_role.watchdog.id
  policy = data.aws_iam_policy_document.watchdog.json
}

resource "aws_cloudwatch_log_group" "watchdog" {
  name              = "/aws/lambda/ne-demand-watchdog"
  retention_in_days = 14
}

resource "aws_lambda_function" "watchdog" {
  function_name    = "ne-demand-watchdog"
  role             = aws_iam_role.watchdog.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.watchdog.output_path
  source_code_hash = data.archive_file.watchdog.output_base64sha256
  timeout          = 30
  memory_size      = 128

  environment {
    variables = {
      BUCKET    = aws_s3_bucket.data.bucket
      TOPIC_ARN = aws_sns_topic.alerts.arn
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.watchdog.name
  }

  depends_on = [aws_iam_role_policy_attachment.watchdog_logs]
}

# --- hourly schedule ---

data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "watchdog_scheduler" {
  name               = "ne-demand-watchdog-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
}

resource "aws_iam_role_policy" "watchdog_scheduler" {
  name = "invoke-watchdog"
  role = aws_iam_role.watchdog_scheduler.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.watchdog.arn }]
  })
}

resource "aws_scheduler_schedule" "watchdog" {
  count               = var.watchdog_schedule_enabled ? 1 : 0
  name                = "ne-demand-watchdog"
  schedule_expression = "rate(1 hour)"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_lambda_function.watchdog.arn
    role_arn = aws_iam_role.watchdog_scheduler.arn
  }
}

output "alerts_topic_arn" {
  description = "Set as the SNS_TOPIC_ARN repository variable"
  value       = aws_sns_topic.alerts.arn
}
