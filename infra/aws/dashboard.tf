# Read-only identity for the public Streamlit app. Streamlit Community Cloud cannot use
# OIDC, so it gets a long-lived key, limited to the two prefixes the app reads.

resource "aws_iam_user" "dashboard" {
  name = "ne-demand-dashboard-reader"
}

data "aws_iam_policy_document" "dashboard_read" {
  statement {
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.data.arn}/published/*",
      "${aws_s3_bucket.data.arn}/processed/*",
    ]
  }
}

resource "aws_iam_user_policy" "dashboard_read" {
  name   = "read-published-and-processed"
  user   = aws_iam_user.dashboard.name
  policy = data.aws_iam_policy_document.dashboard_read.json
}

resource "aws_iam_access_key" "dashboard" {
  user = aws_iam_user.dashboard.name
}

output "dashboard_access_key_id" {
  value = aws_iam_access_key.dashboard.id
}

output "dashboard_secret_access_key" {
  description = "Paste into Streamlit Cloud secrets; read with terraform output -raw"
  value       = aws_iam_access_key.dashboard.secret
  sensitive   = true
}
