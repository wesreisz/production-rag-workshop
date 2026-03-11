resource "aws_db_subnet_group" "aurora" {
  name       = "${var.project_name}-aurora"
  subnet_ids = var.subnet_ids

  tags = merge(var.tags, { Name = "${var.project_name}-aurora-subnet-group" })
}

resource "aws_rds_cluster" "this" {
  cluster_identifier = "${var.project_name}-vectordb"
  engine             = "aurora-postgresql"
  engine_version     = "17.7"
  database_name      = var.db_name
  master_username    = var.master_username
  master_password    = var.master_password

  db_subnet_group_name   = aws_db_subnet_group.aurora.name
  vpc_security_group_ids = [var.security_group_id]

  skip_final_snapshot  = true
  apply_immediately    = true
  enable_http_endpoint = true

  serverlessv2_scaling_configuration {
    min_capacity = 0.5
    max_capacity = 4
  }

  tags = var.tags
}

resource "aws_rds_cluster_instance" "this" {
  identifier         = "${var.project_name}-vectordb-instance"
  cluster_identifier = aws_rds_cluster.this.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.this.engine
  engine_version     = aws_rds_cluster.this.engine_version

  publicly_accessible = false

  tags = var.tags
}

resource "aws_secretsmanager_secret" "db" {
  name = "${var.project_name}-aurora-credentials"

  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id

  secret_string = jsonencode({
    host     = aws_rds_cluster.this.endpoint
    port     = aws_rds_cluster.this.port
    dbname   = var.db_name
    username = var.master_username
    password = var.master_password
  })
}
