output "api_url" {
  description = "Base URL (e.g. https://abc123.execute-api.us-east-1.amazonaws.com/prod)"
  value       = aws_api_gateway_stage.this.invoke_url
}

output "rest_api_id" {
  description = "REST API ID"
  value       = aws_api_gateway_rest_api.this.id
}

output "api_key_value" {
  description = "API key value (use in x-api-key header)"
  value       = aws_api_gateway_api_key.this.value
  sensitive   = true
}
