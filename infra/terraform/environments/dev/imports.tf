###############################################################################
# Import blocks — bring existing AWS resources into state.
#
# These were created by a previous partial apply whose state was lost.
# Run `tofu apply` once to absorb them, then delete this file.
###############################################################################

# ---------------------------------------------------------------------------
# ECR
# ---------------------------------------------------------------------------

import {
  to = module.ecr.aws_ecr_repository.repos["embed-api"]
  id = "embed-anything/embed-api"
}

import {
  to = module.ecr.aws_ecr_repository.repos["embed-pipeline"]
  id = "embed-anything/embed-pipeline"
}

import {
  to = module.ecr.aws_ecr_lifecycle_policy.cleanup["embed-api"]
  id = "embed-anything/embed-api"
}

import {
  to = module.ecr.aws_ecr_lifecycle_policy.cleanup["embed-pipeline"]
  id = "embed-anything/embed-pipeline"
}

# ---------------------------------------------------------------------------
# IAM — ECS API
# ---------------------------------------------------------------------------

import {
  to = module.ecs_api.aws_iam_role.task_execution
  id = "ea-dev-api-exec-role"
}

import {
  to = module.ecs_api.aws_iam_role.task
  id = "ea-dev-api-task-role"
}

# ---------------------------------------------------------------------------
# IAM — Pipeline task
# ---------------------------------------------------------------------------

import {
  to = module.pipeline_task.aws_iam_role.task_execution
  id = "ea-dev-pipeline-exec-role"
}

import {
  to = module.pipeline_task.aws_iam_role.task
  id = "ea-dev-pipeline-task-role"
}

# ---------------------------------------------------------------------------
# CloudWatch log groups
# ---------------------------------------------------------------------------

import {
  to = module.ecs_api.aws_cloudwatch_log_group.api
  id = "/ecs/ea-dev-api"
}

import {
  to = module.pipeline_task.aws_cloudwatch_log_group.pipeline
  id = "/ecs/ea-dev-pipeline"
}

# ---------------------------------------------------------------------------
# Security group rule — pipeline → RDS
# ---------------------------------------------------------------------------

import {
  to = module.pipeline_task.aws_security_group_rule.pipeline_to_rds[0]
  id = "sg-05dc499a6b96b35d1_ingress_tcp_5432_5432_sg-09adbc9e968001b4c"
}

# ---------------------------------------------------------------------------
# RDS
# ---------------------------------------------------------------------------

import {
  to = module.rds.aws_db_subnet_group.main
  id = "ea-dev-pg-subnet-group"
}

import {
  to = module.rds.aws_db_parameter_group.pg15
  id = "ea-dev-pg15-params"
}

import {
  to = module.rds.aws_db_instance.main
  id = "ea-dev-pg"
}

# import {
#  to = module.rds.aws_secretsmanager_secret.db_password
#  id = "arn:aws:secretsmanager:us-east-1:495199591388:secret:ea-dev/rds/master-password-1j6aba"
#}

# import {
#  to = module.rds.aws_secretsmanager_secret_version.db_password
  # Format: "SECRET_ARN|VERSION_ID"
#  id = "arn:aws:secretsmanager:us-east-1:495199591388:secret:ea-dev/rds/master-password-1j6aba|00000000-0000-0000-0000-000000000000"
# }
