###############################################################################
# Pipeline ECS Task Definition
#
# Runs the embed-pipeline as a one-shot Fargate task — zero cost when idle.
# Trigger manually or from EventBridge / Lambda:
#
#   aws ecs run-task \
#     --cluster <cluster-arn> \
#     --task-definition <family>:<revision> \
#     --launch-type FARGATE \
#     --network-configuration "awsvpcConfiguration={subnets=[<subnet>],securityGroups=[<sg>],assignPublicIp=ENABLED}" \
#     --overrides '{"containerOverrides":[{"name":"embed-pipeline","environment":[
#         {"name":"ATHENA_DATABASE","value":"my_db"},
#         {"name":"ATHENA_QUERY","value":"SELECT id, image_s3_uri FROM items"},
#         {"name":"PIPELINE_RUN_ID","value":"run-001"}
#     ]}]}'
#
# Ray runs in LOCAL mode inside the container — no separate cluster needed.
# Size the task (cpu/memory) to match the embedding model:
#   CLIP ViT-B-32  → 4096 MB is comfortable
#   Larger models  → bump to 8192+ MB and 2+ vCPU
###############################################################################

# ---------------------------------------------------------------------------
# ECS cluster (shared with the API service, or standalone)
# ---------------------------------------------------------------------------

resource "aws_ecs_cluster" "pipeline" {
  name = "${var.name}-pipeline-cluster"
  tags = var.tags
}

# ---------------------------------------------------------------------------
# Security group — outbound only (reaches S3, Athena, RDS, ECR via public IP)
# ---------------------------------------------------------------------------

resource "aws_security_group" "pipeline_task" {
  name        = "${var.name}-pipeline-task-sg"
  description = "embed-pipeline ECS task - outbound only"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.name}-pipeline-task-sg" })
}

# Allow pipeline task to reach RDS on 5432
resource "aws_security_group_rule" "pipeline_to_rds" {
  count                    = var.enable_rds_access ? 1 : 0
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.pipeline_task.id
  security_group_id        = var.rds_security_group_id
}

# ---------------------------------------------------------------------------
# IAM
# ---------------------------------------------------------------------------

resource "aws_iam_role" "task_execution" {
  name = "${var.name}-pipeline-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task" {
  name = "${var.name}-pipeline-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "task_inline" {
  name = "pipeline-task-inline"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3ReadWrite"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${var.data_bucket}",
          "arn:aws:s3:::${var.data_bucket}/*",
          "arn:aws:s3:::${var.athena_results_bucket}",
          "arn:aws:s3:::${var.athena_results_bucket}/*",
        ]
      },
      {
        Sid    = "AthenaExecution"
        Effect = "Allow"
        Action = [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:StopQueryExecution",
        ]
        Resource = "*"
      },
      {
        Sid    = "GlueReadCatalog"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetTable",
          "glue:GetPartitions",
        ]
        Resource = "*"
      },
      {
        Sid    = "SecretsRead"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = var.secrets_arns
      },
      {
        Sid    = "BedrockInvoke"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = "*"
      },
    ]
  })
}


# ---------------------------------------------------------------------------
# CloudWatch log group
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "pipeline" {
  name              = "/ecs/${var.name}-pipeline"
  retention_in_days = 14
  tags              = var.tags
}

# ---------------------------------------------------------------------------
# ECS task definition
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "pipeline" {
  family                   = "${var.name}-pipeline"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name      = "embed-pipeline"
    image     = var.container_image
    essential = true

    # Base environment — all values can be overridden per run-task invocation
    environment = [
      # Provider
      { name = "PROVIDER_TYPE",       value = var.provider_type },
      { name = "PROVIDER_MODEL_NAME", value = var.provider_model_name },
      { name = "PROVIDER_PRETRAINED", value = var.provider_pretrained },
      { name = "PROVIDER_DEVICE",     value = "cpu" },

      # Store
      { name = "STORE_TYPE",          value = var.store_type },
      { name = "STORE_DIMENSION",     value = tostring(var.store_dimension) },
      { name = "STORE_PGVECTOR_DSN",  value = var.store_dsn },

      # Athena defaults (override per job via --overrides)
      { name = "ATHENA_RESULTS_BUCKET",  value = var.athena_results_bucket },
      { name = "ATHENA_AWS_REGION",      value = var.aws_region },
      { name = "ATHENA_ID_COLUMN",       value = "id" },
      { name = "ATHENA_IMAGE_URI_COLUMN", value = "image_s3_uri" },

      # Ray — local mode: no external cluster required
      { name = "RAY_ADDRESS",             value = "local" },
      { name = "RAY_NUM_EMBEDDING_ACTORS", value = tostring(var.ray_num_actors) },
      { name = "RAY_BATCH_SIZE",          value = tostring(var.ray_batch_size) },

      # Pipeline
      { name = "PIPELINE_LOG_LEVEL", value = "INFO" },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.pipeline.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "pipeline"
      }
    }
  }])

  tags = var.tags
}
