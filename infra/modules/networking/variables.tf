variable "project_name" {
  description = "Project name prefix for resource naming"
  type        = string
}

variable "aws_region" {
  description = "AWS region for VPC endpoint service names"
  type        = string
}

variable "allowed_cidrs" {
  description = "CIDR blocks allowed to access Aurora directly (e.g. your IP for dev)"
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Resource tags"
  type        = map(string)
  default     = {}
}
