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

variable "allowed_cidrs" {
  description = "CIDR blocks allowed to access Aurora directly (e.g. [\"1.2.3.4/32\"])"
  type        = list(string)
  default     = []
}
