terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "production-rag-tf-state-885268918288"
    key            = "dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "production-rag-tf-lock"
    encrypt        = true
  }
}
