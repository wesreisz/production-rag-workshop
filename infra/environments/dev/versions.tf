terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
  }

  backend "s3" {
    bucket         = "PLACEHOLDER"
    key            = "dev/terraform.tfstate"
    dynamodb_table = "production-rag-tf-lock"
    region         = "us-east-1"
  }
}
