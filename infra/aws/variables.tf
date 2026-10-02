variable "region" {
  type    = string
  default = "us-east-1"
}

variable "github_sub_prefix" {
  description = <<-EOT
    OIDC subject prefix of the repository whose Actions may assume the pipeline role.
    The repo uses GitHub's immutable subject format (owner@id/repo@id), so a renamed or
    re-created repository with the same name cannot assume the role. Read it with
    gh api repos/OWNER/REPO/actions/oidc/customization/sub
  EOT
  type        = string
  default     = "repo:vladimir-kazarin@18403526/ne-demand-forecast@1402344956"
}

variable "create_github_oidc_provider" {
  description = "Set false if the account already has the token.actions.githubusercontent.com provider"
  type        = bool
  default     = true
}

variable "monthly_budget_usd" {
  description = "PRD cost ceiling; alerts at 80% actual and 100% forecast"
  type        = number
  default     = 20
}

variable "alert_email" {
  description = "Where budget alerts are sent (set in terraform.tfvars, which is gitignored)"
  type        = string
}
