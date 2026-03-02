variable "bucket_name" {
  type = string
}

variable "enable_eventbridge" {
  type    = bool
  default = true
}

variable "tags" {
  type    = map(string)
  default = {}
}
