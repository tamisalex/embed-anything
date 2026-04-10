output "head_private_ip" {
  value = aws_instance.head.private_ip
}

output "head_public_ip" {
  value = aws_instance.head.public_ip
}

output "ray_address" {
  description = "Ray cluster address to pass to ray.init()"
  value       = "${aws_instance.head.private_ip}:6379"
}

output "dashboard_url" {
  value = "http://${aws_instance.head.public_ip}:8265"
}

output "worker_asg_name" {
  value = aws_autoscaling_group.workers.name
}

output "head_security_group_id" {
  value = aws_security_group.ray_head.id
}

output "worker_security_group_id" {
  value = aws_security_group.ray_worker.id
}

output "iam_role_arn" {
  value = aws_iam_role.ray_node.arn
}
