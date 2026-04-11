###############################################################################
# ECS Fargate service — embed-api (FastAPI)
#
# Two modes controlled by var.enable_alb:
#
#   enable_alb = true  — ALB in front, port 80 public  (~$16/month)
#   enable_alb = false — task gets a public IP, port 8080 locked to
#                        var.allowed_cidr (default: your IP only). Free.
###############################################################################

# ---------------------------------------------------------------------------
# Security group — task
# ---------------------------------------------------------------------------

resource "aws_security_group" "ecs_task" {
  name        = "${var.name}-api-task-sg"
  description = "embed-api ECS task"
  vpc_id      = var.vpc_id

  # When ALB is enabled: only accept traffic from the ALB SG
  dynamic "ingress" {
    for_each = var.enable_alb ? [1] : []
    content {
      from_port       = 8080
      to_port         = 8080
      protocol        = "tcp"
      security_groups = [aws_security_group.alb[0].id]
    }
  }

  # When ALB is disabled: accept traffic directly from allowed CIDRs
  dynamic "ingress" {
    for_each = var.enable_alb ? [] : [1]
    content {
      from_port   = 8080
      to_port     = 8080
      protocol    = "tcp"
      cidr_blocks = var.allowed_cidr
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.name}-api-task-sg" })
}

# ---------------------------------------------------------------------------
# ALB (optional)
# ---------------------------------------------------------------------------

resource "aws_security_group" "alb" {
  count       = var.enable_alb ? 1 : 0
  name        = "${var.name}-api-alb-sg"
  description = "Allow inbound HTTP to ALB"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.name}-api-alb-sg" })
}

resource "aws_lb" "api" {
  count              = var.enable_alb ? 1 : 0
  name               = "${var.name}-api-alb"
  internal           = false
  load_balancer_type = "application"
  subnets            = var.public_subnet_ids
  security_groups    = [aws_security_group.alb[0].id]
  tags               = var.tags
}

resource "aws_lb_target_group" "api" {
  count       = var.enable_alb ? 1 : 0
  name        = "${var.name}-api-tg"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/healthz"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = var.tags
}

resource "aws_lb_listener" "http" {
  count             = var.enable_alb ? 1 : 0
  load_balancer_arn = aws_lb.api[0].arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api[0].arn
  }
}

# ---------------------------------------------------------------------------
# IAM
# ---------------------------------------------------------------------------

resource "aws_iam_role" "task_execution" {
  name = "${var.name}-api-exec-role"

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

# ECS secrets injection uses the execution role — not the task role
resource "aws_iam_role_policy" "task_execution_secrets" {
  name = "api-exec-secrets"
  role = aws_iam_role.task_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [var.store_dsn_secret_arn]
    }]
  })
}

resource "aws_iam_role" "task" {
  name = "${var.name}-api-task-role"

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
  name = "api-task-inline"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      length(var.secrets_arns) > 0 ? [{
        Sid      = "SecretsRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = var.secrets_arns
      }] : [],
      [{
        Sid      = "BedrockInvoke"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = "*"
      }]
    )
  })
}

# ---------------------------------------------------------------------------
# CloudWatch log group
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.name}-api"
  retention_in_days = 7
  tags              = var.tags
}

# ---------------------------------------------------------------------------
# ECS cluster + task definition + service
# ---------------------------------------------------------------------------

resource "aws_ecs_cluster" "api" {
  name = "${var.name}-api-cluster"
  tags = var.tags
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name      = "embed-api"
    image     = var.container_image
    essential = true

    portMappings = [{
      containerPort = 8080
      protocol      = "tcp"
    }]

    environment = [
      { name = "PROVIDER_TYPE",       value = var.provider_type },
      { name = "PROVIDER_MODEL_NAME", value = var.provider_model_name },
      { name = "PROVIDER_PRETRAINED", value = var.provider_pretrained },
      { name = "PROVIDER_DEVICE",     value = "cpu" },
      { name = "STORE_TYPE",      value = var.store_type },
      { name = "STORE_DIMENSION", value = tostring(var.store_dimension) },
      { name = "API_LOG_LEVEL",       value = "INFO" },
    ]

    secrets = [
      { name = "STORE_PGVECTOR_DSN", valueFrom = var.store_dsn_secret_arn }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "api"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:8080/healthz || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
  }])

  tags = var.tags
}

resource "aws_ecs_service" "api" {
  name            = "${var.name}-api"
  cluster         = aws_ecs_cluster.api.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [aws_security_group.ecs_task.id]
    assign_public_ip = true
  }

  dynamic "load_balancer" {
    for_each = var.enable_alb ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.api[0].arn
      container_name   = "embed-api"
      container_port   = 8080
    }
  }

  depends_on = [aws_lb_listener.http]

  tags = var.tags
}
