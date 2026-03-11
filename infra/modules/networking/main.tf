data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

data "aws_route_tables" "default" {
  vpc_id = data.aws_vpc.default.id
}

resource "aws_security_group" "lambda" {
  name        = "${var.project_name}-lambda-sg"
  description = "Security group for Lambda functions"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTPS from self for VPC interface endpoints"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    self        = true
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.project_name}-lambda-sg" })
}

resource "aws_security_group" "aurora" {
  name        = "${var.project_name}-aurora-sg"
  description = "Security group for Aurora cluster"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id, aws_security_group.cloudshell.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.project_name}-aurora-sg" })
}

resource "aws_security_group" "cloudshell" {
  name        = "${var.project_name}-cloudshell-sg"
  description = "Security group for CloudShell VPC environments"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.project_name}-cloudshell-sg" })
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_subnet" "cloudshell" {
  vpc_id            = data.aws_vpc.default.id
  cidr_block        = "172.31.100.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]

  tags = merge(var.tags, { Name = "${var.project_name}-cloudshell-subnet" })
}

resource "aws_eip" "nat" {
  domain = "vpc"

  tags = merge(var.tags, { Name = "${var.project_name}-nat-eip" })
}

resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = tolist(data.aws_subnets.default.ids)[0]

  tags = merge(var.tags, { Name = "${var.project_name}-nat" })
}

resource "aws_route_table" "cloudshell" {
  vpc_id = data.aws_vpc.default.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this.id
  }

  tags = merge(var.tags, { Name = "${var.project_name}-cloudshell-rt" })
}

resource "aws_route_table_association" "cloudshell" {
  subnet_id      = aws_subnet.cloudshell.id
  route_table_id = aws_route_table.cloudshell.id
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id          = data.aws_vpc.default.id
  service_name    = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids = data.aws_route_tables.default.ids

  tags = merge(var.tags, { Name = "${var.project_name}-s3-endpoint" })
}

resource "aws_vpc_endpoint" "bedrock" {
  vpc_id              = data.aws_vpc.default.id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = data.aws_subnets.default.ids
  security_group_ids  = [aws_security_group.lambda.id]
  private_dns_enabled = true

  tags = merge(var.tags, { Name = "${var.project_name}-bedrock-endpoint" })
}

resource "aws_vpc_endpoint" "secretsmanager" {
  vpc_id              = data.aws_vpc.default.id
  service_name        = "com.amazonaws.${var.aws_region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = data.aws_subnets.default.ids
  security_group_ids  = [aws_security_group.lambda.id]
  private_dns_enabled = true

  tags = merge(var.tags, { Name = "${var.project_name}-secretsmanager-endpoint" })
}
