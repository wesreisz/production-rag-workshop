variable "function_name" {
  type        = string
  description = "Lambda function name"
}

variable "handler" {
  type        = string
  description = "Handler path (e.g. src.handlers.start_transcription.handler)"
}

variable "runtime" {
  type        = string
  default     = "python3.11"
  description = "Lambda runtime"
}

variable "timeout" {
  type        = number
  default     = 30
  description = "Timeout in seconds"
}

variable "memory_size" {
  type        = number
  default     = 256
  description = "Memory in MB"
}

variable "source_dir" {
  type        = string
  description = "Absolute path to Python source directory to zip"
}

variable "environment_variables" {
  type        = map(string)
  default     = {}
  description = "Environment variables"
}

variable "policy_statements" {
  type        = string
  description = "JSON-encoded IAM policy document for function-specific permissions"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Resource tags"
}

variable "subnet_ids" {
  type        = list(string)
  description = "Subnet IDs for Lambda VPC configuration"
}

variable "security_group_ids" {
  type        = list(string)
  description = "Security group IDs for Lambda VPC configuration"
}

variable "layers" {
  type        = list(string)
  default     = []
  description = "Lambda layer ARNs"
}
