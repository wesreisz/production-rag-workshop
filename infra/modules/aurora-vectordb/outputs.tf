output "cluster_endpoint" {
  value = aws_rds_cluster.this.endpoint
}

output "cluster_port" {
  value = aws_rds_cluster.this.port
}

output "secret_arn" {
  value = aws_secretsmanager_secret.db.arn
}

output "cluster_arn" {
  value = aws_rds_cluster.this.arn
}

output "db_name" {
  value = var.db_name
}
