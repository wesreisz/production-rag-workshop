output "vpc_id" {
  description = "Default VPC ID"
  value       = data.aws_vpc.default.id
}

output "subnet_ids" {
  description = "Default VPC subnet IDs"
  value       = data.aws_subnets.default.ids
}

output "lambda_security_group_id" {
  description = "Security group for Lambda functions"
  value       = aws_security_group.lambda.id
}

output "aurora_security_group_id" {
  description = "Security group for Aurora cluster"
  value       = aws_security_group.aurora.id
}

output "cloudshell_subnet_id" {
  description = "Private subnet for CloudShell VPC environments"
  value       = aws_subnet.cloudshell.id
}

output "cloudshell_security_group_id" {
  description = "Security group for CloudShell VPC environments"
  value       = aws_security_group.cloudshell.id
}
