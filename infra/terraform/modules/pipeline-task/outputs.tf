output "cluster_arn" {
  value = aws_ecs_cluster.pipeline.arn
}

output "cluster_name" {
  value = aws_ecs_cluster.pipeline.name
}

output "task_definition_arn" {
  value = aws_ecs_task_definition.pipeline.arn
}

output "task_definition_family" {
  value = aws_ecs_task_definition.pipeline.family
}

output "task_security_group_id" {
  value = aws_security_group.pipeline_task.id
}

output "task_role_arn" {
  value = aws_iam_role.task.arn
}

output "execution_role_arn" {
  value = aws_iam_role.task_execution.arn
}


output "log_group_name" {
  value = aws_cloudwatch_log_group.pipeline.name
}

output "run_task_command" {
  description = "Example AWS CLI command to trigger a pipeline run"
  value = <<-CMD
    aws ecs run-task \
      --cluster ${aws_ecs_cluster.pipeline.arn} \
      --task-definition ${aws_ecs_task_definition.pipeline.family} \
      --launch-type FARGATE \
      --network-configuration 'awsvpcConfiguration={subnets=["SUBNET_ID"],securityGroups=["${aws_security_group.pipeline_task.id}"],assignPublicIp="ENABLED"}' \
      --overrides '{"containerOverrides":[{"name":"embed-pipeline","environment":[
        {"name":"ATHENA_DATABASE","value":"YOUR_DB"},
        {"name":"ATHENA_QUERY","value":"SELECT id, image_s3_uri FROM items LIMIT 1000"},
        {"name":"PIPELINE_INDEX","value":"items"},
        {"name":"PIPELINE_RUN_ID","value":"run-001"}
      ]}]}'
  CMD
}
