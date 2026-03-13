variable "project_name" {
  type = string
}

variable "state_machine_definition" {
  type        = string
  description = "JSON-encoded state machine definition"
}

variable "lambda_arns" {
  type        = list(string)
  description = "Lambda ARNs the state machine is allowed to invoke"
}

variable "s3_bucket_name" {
  type        = string
  description = "S3 bucket name for the EventBridge upload trigger"
}

variable "s3_key_prefix" {
  type    = string
  default = "uploads/"
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "tags" {
  type    = map(string)
  default = {}
}
