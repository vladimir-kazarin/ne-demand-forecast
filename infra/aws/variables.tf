variable "region" {
  type    = string
  default = "us-east-1"
}

variable "github_repo" {
  description = "owner/name of the repository whose Actions may assume the pipeline role"
  type        = string
  default     = "vladimir-kazarin/ne-demand-forecast"
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
