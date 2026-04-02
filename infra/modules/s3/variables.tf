variable "bucket_name" {
  description = "Full S3 bucket name"
  type        = string
}

variable "enable_eventbridge" {
  description = "Enable EventBridge notifications for this bucket"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Resource tags"
  type        = map(string)
  default     = {}
}
