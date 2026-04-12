variable "bucket_name" {
  type        = string
  description = "Full bucket name"
}

variable "enable_eventbridge" {
  type        = bool
  default     = true
  description = "Enable EventBridge notifications"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Resource tags"
}
