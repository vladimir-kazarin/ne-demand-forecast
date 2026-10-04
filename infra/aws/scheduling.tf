# Job scheduling: EventBridge Scheduler -> dispatcher Lambda -> GitHub workflow_dispatch.
#
# GitHub's cron dropped most runs on some days (docs/incidents.md, ADR 0009). Scheduler
# fires on time and understands time zones; the dispatcher turns each firing into a
# workflow_dispatch, which GitHub starts immediately. The watchdog (monitoring.tf)
# still alerts if anything is missed, including the dispatcher itself.

locals {
  github_repo        = "vladimir-kazarin/ne-demand-forecast"
  dispatch_token_ssm = "/ne-demand/github-dispatch-token" # created by hand; never in state

  schedules = {
    ingest = {
      expression = "cron(17 * * * ? *)" # hourly
      timezone   = "UTC"
      workflow   = "ingest.yml"
    }
    monitor = {
      expression = "cron(47 * * * ? *)" # hourly, 30 min after ingest
      timezone   = "UTC"
      workflow   = "monitor.yml"
    }
    forecast = {
      expression = "cron(32 10 * * ? *)" # 10:32 ET all year; AWS handles DST (ADR 0004)
      timezone   = "America/New_York"
      workflow   = "forecast.yml"
    }
  }
}

data "archive_file" "dispatcher" {
  type        = "zip"
  source_file = "${path.module}/dispatcher/handler.py"
  output_path = "${path.module}/.build/dispatcher.zip"
}

resource "aws_iam_role" "dispatcher" {
  name               = "ne-demand-dispatcher"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "dispatcher_logs" {
  role       = aws_iam_role.dispatcher.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "dispatcher" {
  statement {
    sid       = "ReadDispatchToken"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${local.dispatch_token_ssm}"]
  }
  statement {
    sid       = "DecryptViaSsmOnly"
    actions   = ["kms:Decrypt"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "dispatcher" {
  name   = "read-dispatch-token"
  role   = aws_iam_role.dispatcher.id
  policy = data.aws_iam_policy_document.dispatcher.json
}

resource "aws_cloudwatch_log_group" "dispatcher" {
  name              = "/aws/lambda/ne-demand-dispatcher"
  retention_in_days = 14
}

resource "aws_lambda_function" "dispatcher" {
  function_name    = "ne-demand-dispatcher"
  role             = aws_iam_role.dispatcher.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.dispatcher.output_path
  source_code_hash = data.archive_file.dispatcher.output_base64sha256
  timeout          = 30
  memory_size      = 128

  environment {
    variables = {
      REPO        = local.github_repo
      TOKEN_PARAM = local.dispatch_token_ssm
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.dispatcher.name
  }

  depends_on = [aws_iam_role_policy_attachment.dispatcher_logs]
}

resource "aws_iam_role" "dispatch_scheduler" {
  name               = "ne-demand-dispatch-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
}

resource "aws_iam_role_policy" "dispatch_scheduler" {
  name = "invoke-dispatcher"
  role = aws_iam_role.dispatch_scheduler.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.dispatcher.arn }]
  })
}

resource "aws_scheduler_schedule" "jobs" {
  for_each                     = local.schedules
  name                         = "ne-demand-${each.key}"
  schedule_expression          = each.value.expression
  schedule_expression_timezone = each.value.timezone
  flexible_time_window { mode = "OFF" }

  target {
    arn      = aws_lambda_function.dispatcher.arn
    role_arn = aws_iam_role.dispatch_scheduler.arn
    input    = jsonencode({ workflow = each.value.workflow })
    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 1800
    }
  }
}
