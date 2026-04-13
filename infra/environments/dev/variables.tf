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
  type        = string
  sensitive   = true
  description = "Aurora master password"
}
