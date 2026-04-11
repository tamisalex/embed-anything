output "endpoint" {
  value = aws_db_instance.main.endpoint
}

output "db_name" {
  value = aws_db_instance.main.db_name
}

output "db_username" {
  value = aws_db_instance.main.username
}

output "password_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the master password"
  value       = aws_secretsmanager_secret.db_password.arn
}

output "security_group_id" {
  value = aws_security_group.rds.id
}

output "dsn_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the full DSN — pass to ECS secrets injection"
  value       = aws_secretsmanager_secret.db_dsn.arn
}
