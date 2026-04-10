output "repository_urls" {
  description = "Map of repository name → ECR URL"
  value       = { for k, v in aws_ecr_repository.repos : k => v.repository_url }
}

output "repository_arns" {
  description = "Map of repository name → ECR ARN"
  value       = { for k, v in aws_ecr_repository.repos : k => v.arn }
}

output "registry_id" {
  value = values(aws_ecr_repository.repos)[0].registry_id
}
