variable "project_name" {
  description = "Project name used to derive all resource names"
  type        = string
}

variable "definition" {
  description = "State machine definition JSON"
  type        = string
}

variable "source_bucket_name" {
  description = "S3 bucket name for EventBridge event pattern"
  type        = string
}

variable "object_key_prefix" {
  description = "S3 object key prefix for EventBridge event pattern"
  type        = string
  default     = "uploads/"
}

variable "additional_policy_json" {
  description = "Additional IAM policy JSON to attach to the execution role"
  type        = string
  default     = null
}

variable "tags" {
  description = "Resource tags"
  type        = map(string)
  default     = {}
}
