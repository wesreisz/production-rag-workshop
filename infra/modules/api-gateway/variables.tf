variable "api_name" {
  description = "REST API name"
  type        = string
}

variable "lambda_invoke_arn" {
  description = "Lambda function invoke ARN"
  type        = string
}

variable "lambda_function_name" {
  description = "Lambda function name (for permission resource)"
  type        = string
}

variable "stage_name" {
  description = "API Gateway stage name"
  type        = string
  default     = "prod"
}

variable "tags" {
  description = "Resource tags"
  type        = map(string)
  default     = {}
}
