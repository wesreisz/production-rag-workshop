output "cluster_endpoint" {
  description = "Aurora cluster writer endpoint"
  value       = aws_rds_cluster.this.endpoint
}

output "cluster_port" {
  description = "Aurora cluster port (5432)"
  value       = aws_rds_cluster.this.port
}

output "secret_arn" {
  description = "Secrets Manager secret ARN"
  value       = aws_secretsmanager_secret.db.arn
}

output "cluster_arn" {
  description = "Aurora cluster ARN"
  value       = aws_rds_cluster.this.arn
}

output "db_name" {
  description = "Database name"
  value       = var.db_name
}
