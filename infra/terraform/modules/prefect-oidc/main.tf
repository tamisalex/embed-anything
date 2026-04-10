###############################################################################
# Prefect Cloud OIDC — federated identity for Prefect Managed work pool
#
# Instead of storing static IAM access keys in Prefect Cloud, this lets
# Prefect Cloud exchange a short-lived OIDC token for temporary AWS
# credentials via STS AssumeRoleWithWebIdentity.
#
# How it works:
#   1. Prefect Managed runner issues a signed OIDC JWT for the flow run
#   2. prefect-aws calls sts:AssumeRoleWithWebIdentity with that JWT
#   3. STS validates the JWT against api.prefect.cloud/auth/oidc/ and
#      returns short-lived credentials scoped to this role
#   4. The role can call ecs:RunTask / ecs:DescribeTasks to trigger the
#      pipeline Fargate task — nothing else
###############################################################################

# ---------------------------------------------------------------------------
# OIDC identity provider — tells AWS to trust Prefect Cloud's token issuer
# ---------------------------------------------------------------------------

data "tls_certificate" "prefect" {
  url = "https://api.prefect.cloud/auth/oidc/"
}

resource "aws_iam_openid_connect_provider" "prefect" {
  url             = "https://api.prefect.cloud/auth/oidc/"
  client_id_list  = [var.prefect_account_id]   # audience claim in the JWT
  thumbprint_list = [data.tls_certificate.prefect.certificates[0].sha1_fingerprint]
  tags            = var.tags
}

# ---------------------------------------------------------------------------
# IAM role — assumed by Prefect Cloud when a flow run starts
# ---------------------------------------------------------------------------

resource "aws_iam_role" "prefect_runner" {
  name        = "${var.name}-prefect-runner"
  description = "Assumed by Prefect Managed work pool via OIDC to trigger ECS pipeline tasks"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.prefect.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        # Scope to your Prefect account; optionally add workspace:
        #   "prefect:account:<id>:workspace:<workspace_id>:*"
        StringLike = {
          "api.prefect.cloud/auth/oidc/:sub" = "prefect:account:${var.prefect_account_id}:*"
        }
        StringEquals = {
          "api.prefect.cloud/auth/oidc/:aud" = var.prefect_account_id
        }
      }
    }]
  })

  tags = var.tags
}

# ---------------------------------------------------------------------------
# Inline policy — minimum permissions to trigger and monitor the ECS task
# ---------------------------------------------------------------------------

resource "aws_iam_role_policy" "prefect_runner_inline" {
  name = "prefect-runner-ecs"
  role = aws_iam_role.prefect_runner.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ECSRunAndMonitor"
        Effect = "Allow"
        Action = [
          "ecs:RunTask",
          "ecs:DescribeTasks",
          "ecs:ListTasks",
          "ecs:StopTask",
        ]
        Resource = "*"
        Condition = {
          ArnLike = {
            "ecs:cluster" = var.pipeline_cluster_arn
          }
        }
      },
      {
        # ECS needs to receive the task/execution roles when launching Fargate tasks
        Sid    = "PassECSRoles"
        Effect = "Allow"
        Action = "iam:PassRole"
        Resource = var.ecs_role_arns
        Condition = {
          StringLike = {
            "iam:PassedToService" = "ecs-tasks.amazonaws.com"
          }
        }
      },
    ]
  })
}
