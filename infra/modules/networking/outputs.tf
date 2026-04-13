output "vpc_id" {
  value = data.aws_vpc.default.id
}

output "subnet_ids" {
  value = data.aws_subnets.default.ids
}

output "lambda_security_group_id" {
  value = aws_security_group.lambda.id
}

output "aurora_security_group_id" {
  value = aws_security_group.aurora.id
}
