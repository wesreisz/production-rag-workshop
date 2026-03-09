variable "environment" {
  type    = string
  default = "dev"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type    = string
  default = "production-rag"
}

variable "aurora_master_password" {
  description = "Aurora master password. Pass via TF_VAR_aurora_master_password or -var"
  type        = string
  sensitive   = true
}

