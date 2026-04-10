output "alb_dns_name" {
  description = "ALB DNS name (empty string when enable_alb = false)"
  value       = var.enable_alb ? aws_lb.api[0].dns_name : ""
}

output "service_name" {
  value = aws_ecs_service.api.name
}

output "cluster_name" {
  value = aws_ecs_cluster.api.name
}

output "task_security_group_id" {
  value = aws_security_group.ecs_task.id
}
