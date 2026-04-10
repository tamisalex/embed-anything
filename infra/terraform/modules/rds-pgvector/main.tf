###############################################################################
# RDS PostgreSQL with pgvector
#
# Free tier: db.t4g.micro, 20 GB gp2 storage, 750 hours/month
# The pgvector extension is available on Aurora PostgreSQL 15.2+ and
# RDS PostgreSQL 15.2+.
###############################################################################

resource "aws_db_subnet_group" "main" {
  name       = "${var.name}-pg-subnet-group"
  subnet_ids = var.subnet_ids
  tags       = var.tags
}

resource "aws_security_group" "rds" {
  name        = "${var.name}-rds-sg"
  description = "Allow PostgreSQL traffic from ECS tasks"
  vpc_id      = var.vpc_id

  ingress {
    description     = "PostgreSQL from ECS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = var.allowed_security_group_ids
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "random_password" "db" {
  length  = 24
  special = false
}

resource "aws_secretsmanager_secret" "db_password" {
  name                    = "${var.name}/rds/master-password"
  recovery_window_in_days = 0  # immediate delete — fine for dev
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = random_password.db.result
}

resource "aws_db_instance" "main" {
  identifier        = "${var.name}-pg"
  engine            = "postgres"
  engine_version    = "15.7"
  instance_class    = var.instance_class  # db.t4g.micro for free tier
  allocated_storage = var.allocated_storage
  storage_type      = "gp2"

  db_name  = var.db_name
  username = var.db_username
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = false  # single-AZ for free tier

  # Enable pgvector via parameter group
  parameter_group_name = aws_db_parameter_group.pg15.name

  backup_retention_period = 0  # free tier does not allow automated backups
  skip_final_snapshot     = true
  deletion_protection     = var.deletion_protection

  tags = var.tags
}

resource "aws_db_parameter_group" "pg15" {
  name   = "${var.name}-pg15-params"
  family = "postgres15"

  # shared_preload_libraries is required for pgvector on RDS
  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements"
    apply_method = "pending-reboot"
  }

  tags = var.tags
}
