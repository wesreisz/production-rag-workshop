variable "function_name" {
  description = "Lambda function name"
  type        = string
}

variable "handler" {
  description = "Handler path (e.g. src.handlers.start_transcription.handler)"
  type        = string
}

variable "runtime" {
  description = "Lambda runtime"
  type        = string
  default     = "python3.11"
}

variable "timeout" {
  description = "Timeout in seconds"
  type        = number
  default     = 30
}

variable "memory_size" {
  description = "Memory in MB"
  type        = number
  default     = 256
}

variable "source_dir" {
  description = "Absolute path to Python source directory to zip"
  type        = string
}

variable "environment_variables" {
  description = "Environment variables"
  type        = map(string)
  default     = {}
}

variable "policy_statements" {
  description = "JSON-encoded IAM policy document for function-specific permissions"
  type        = string
}

variable "tags" {
  description = "Resource tags"
  type        = map(string)
  default     = {}
}

variable "excludes" {
  description = "Glob patterns to exclude from the Lambda zip"
  type        = list(string)
  default = [
    "**/.venv/**",
    "**/.pytest_cache/**",
    "**/__pycache__/**",
    "**/tests/**",
    "**/*.pyc",
  ]
}
