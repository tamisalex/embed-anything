output "api_url" {
  description = "Search API base URL. With enable_alb=false the public IP is assigned at runtime — find it in the ECS console or with: aws ecs describe-tasks"
  value       = module.ecs_api.alb_dns_name != "" ? "http://${module.ecs_api.alb_dns_name}" : "http://<task-public-ip>:8080  (see: aws ecs describe-tasks --cluster ${module.ecs_api.cluster_name} --tasks $(aws ecs list-tasks --cluster ${module.ecs_api.cluster_name} --query 'taskArns[0]' --output text))"
}

output "pipeline_cluster_arn" {
  description = "ECS cluster ARN to pass to run-task"
  value       = module.pipeline_task.cluster_arn
}

output "pipeline_task_definition" {
  description = "ECS task definition family name"
  value       = module.pipeline_task.task_definition_family
}

output "pipeline_task_sg_id" {
  description = "Security group ID to pass to run-task --network-configuration"
  value       = module.pipeline_task.task_security_group_id
}

output "pipeline_log_group" {
  description = "CloudWatch log group for pipeline runs"
  value       = module.pipeline_task.log_group_name
}

output "pipeline_execution_role_arn" {
  description = "Paste into prefect.yaml job_variables.execution_role_arn"
  value       = module.pipeline_task.execution_role_arn
}

output "pipeline_task_role_arn" {
  description = "Paste into prefect.yaml job_variables.task_role_arn"
  value       = module.pipeline_task.task_role_arn
}


output "pipeline_run_task_example" {
  description = "Example CLI command to trigger a pipeline run"
  value       = module.pipeline_task.run_task_command
}

output "ecr_pipeline_url" {
  value = module.ecr.repository_urls["embed-pipeline"]
}

output "ecr_api_url" {
  value = module.ecr.repository_urls["embed-api"]
}

output "rds_endpoint" {
  value = module.rds.endpoint
}

output "rds_password_secret_arn" {
  value = module.rds.password_secret_arn
}

output "rds_dsn_secret_arn" {
  description = "Secrets Manager ARN for the full DSN (useful for local testing or other consumers)"
  value       = module.rds.dsn_secret_arn
}

output "prefect_runner_role_arn" {
  description = "Paste this into create_prefect_blocks.py as ROLE_ARN — no static keys needed"
  value       = module.prefect_oidc.role_arn
}

output "github_actions_role_arn" {
  description = "Set as ROLE_ARN in .github/workflows/docker_build_action.yaml"
  value       = module.github_oidc.role_arn
}
