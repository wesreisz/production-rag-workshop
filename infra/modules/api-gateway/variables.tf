variable "api_name" {
  type        = string
  description = "REST API name"
}

variable "lambda_invoke_arn" {
  type        = string
  description = "Lambda function invoke ARN"
}

variable "lambda_function_name" {
  type        = string
  description = "Lambda function name (for permission resource)"
}

variable "stage_name" {
  type        = string
  default     = "prod"
  description = "API Gateway stage name"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Resource tags"
}
