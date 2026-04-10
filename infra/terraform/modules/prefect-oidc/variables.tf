variable "name" {
  description = "Resource name prefix"
  type        = string
}

variable "prefect_account_id" {
  description = "Prefect Cloud account ID — find it at app.prefect.cloud/settings (UUID format)"
  type        = string
}

variable "pipeline_cluster_arn" {
  description = "ARN of the ECS cluster the Prefect role is allowed to target"
  type        = string
}

variable "ecs_role_arns" {
  description = "ARNs of the ECS task role and task execution role that Prefect must pass to RunTask"
  type        = list(string)
}

variable "tags" {
  type    = map(string)
  default = {}
}
