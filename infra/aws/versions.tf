terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }

  # Bucket name comes from infra/bootstrap; pass it with
  #   terraform init -backend-config="bucket=ne-demand-tfstate-<account_id>"
  backend "s3" {
    key          = "aws/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { Project = "ne-demand-forecast", ManagedBy = "terraform" } }
}
