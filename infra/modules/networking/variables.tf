variable "project_name" {
  type        = string
  description = "Prefix for resource names"
}

variable "aws_region" {
  type        = string
  description = "AWS region for endpoint service names"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Resource tags"
}
