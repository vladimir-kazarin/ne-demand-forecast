output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "data_root" {
  description = "Value for NE_DATA_ROOT"
  value       = "s3://${aws_s3_bucket.data.bucket}"
}

output "github_actions_role_arn" {
  description = "Set as the AWS_ROLE_ARN repository variable"
  value       = aws_iam_role.pipeline.arn
}
