###############################################################################
# Ray Cluster on EC2
#
# Topology:
#   1 × head node  (t3.medium — 2 vCPU / 4 GB)   ← Ray scheduler + dashboard
#   N × worker nodes (t3.small — 2 vCPU / 2 GB)  ← embedding workers
#
# Free-tier note:
#   t2.micro / t3.micro have 1 GB RAM — too small for most embedding models.
#   t3.medium (head) is ~$0.04/hr; t3.small (worker) is ~$0.02/hr.
#   Spot instances are used to cut cost by ~70 %.
#
# The head node runs the Ray GCS + Dashboard on ports 6379 / 8265.
# Workers connect to the head via the INTERNAL IP — no NAT gateway required
# when all nodes are in the same public subnet.
###############################################################################

locals {
  head_name   = "${var.name}-ray-head"
  worker_name = "${var.name}-ray-worker"
}

# ---------------------------------------------------------------------------
# Security groups
# ---------------------------------------------------------------------------

resource "aws_security_group" "ray_head" {
  name        = "${local.head_name}-sg"
  description = "Ray head node"
  vpc_id      = var.vpc_id

  # Ray GCS port (Redis-compatible)
  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ray_worker.id]
  }

  # Ray dashboard
  ingress {
    from_port   = 8265
    to_port     = 8265
    protocol    = "tcp"
    cidr_blocks = var.dashboard_cidr_allowlist
  }

  # Ray object store (plasma) and inter-node
  ingress {
    from_port       = 10000
    to_port         = 19999
    protocol        = "tcp"
    security_groups = [aws_security_group.ray_worker.id]
  }

  # SSH (optional, tighten in prod)
  dynamic "ingress" {
    for_each = var.ssh_key_name != "" ? [1] : []
    content {
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = var.dashboard_cidr_allowlist
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${local.head_name}-sg" })
}

resource "aws_security_group" "ray_worker" {
  name        = "${local.worker_name}-sg"
  description = "Ray worker nodes"
  vpc_id      = var.vpc_id

  # Allow all intra-cluster traffic (head ↔ workers)
  ingress {
    from_port = 0
    to_port   = 65535
    protocol  = "tcp"
    self      = true
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${local.worker_name}-sg" })
}

# Allow workers → head
resource "aws_security_group_rule" "worker_to_head" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 65535
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ray_worker.id
  security_group_id        = aws_security_group.ray_head.id
}

# ---------------------------------------------------------------------------
# IAM role for EC2 instances (allows ECR pull, S3, Secrets Manager, Athena)
# ---------------------------------------------------------------------------

resource "aws_iam_role" "ray_node" {
  name = "${var.name}-ray-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ray_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "ray_node_inline" {
  name = "ray-node-inline"
  role = aws_iam_role.ray_node.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3ReadSource"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket", "s3:PutObject"]
        Resource = ["arn:aws:s3:::${var.data_bucket}", "arn:aws:s3:::${var.data_bucket}/*"]
      },
      {
        Sid    = "AthenaExecution"
        Effect = "Allow"
        Action = [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
        ]
        Resource = "*"
      },
      {
        Sid    = "GlueReadCatalog"
        Effect = "Allow"
        Action = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartitions"]
        Resource = "*"
      },
      {
        Sid    = "SecretsRead"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = var.secrets_arns
      },
      {
        Sid    = "ECRPull"
        Effect = "Allow"
        Action = [
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:GetAuthorizationToken",
        ]
        Resource = "*"
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

resource "aws_iam_instance_profile" "ray_node" {
  name = "${var.name}-ray-node-profile"
  role = aws_iam_role.ray_node.name
}

# ---------------------------------------------------------------------------
# Latest Amazon Linux 2023 AMI
# ---------------------------------------------------------------------------

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ---------------------------------------------------------------------------
# Head node user-data — installs Ray, starts head
# ---------------------------------------------------------------------------

locals {
  head_userdata = <<-EOF
    #!/bin/bash
    set -euxo pipefail

    # System deps
    dnf install -y python3.11 python3.11-pip docker git
    systemctl enable --now docker
    usermod -aG docker ec2-user

    # Python env
    python3.11 -m pip install --upgrade pip
    python3.11 -m pip install "ray[default]==${var.ray_version}" boto3 structlog

    # Write Ray head start script
    cat > /usr/local/bin/start-ray-head.sh <<'SCRIPT'
    #!/bin/bash
    ray start --head \
      --port=6379 \
      --dashboard-host=0.0.0.0 \
      --dashboard-port=8265 \
      --num-cpus=$(nproc) \
      --block
    SCRIPT
    chmod +x /usr/local/bin/start-ray-head.sh

    # Systemd unit
    cat > /etc/systemd/system/ray-head.service <<'SVC'
    [Unit]
    Description=Ray Head Node
    After=network.target

    [Service]
    User=ec2-user
    ExecStart=/usr/local/bin/start-ray-head.sh
    Restart=on-failure
    RestartSec=10

    [Install]
    WantedBy=multi-user.target
    SVC

    systemctl daemon-reload
    systemctl enable --now ray-head
  EOF

  worker_userdata = <<-EOF
    #!/bin/bash
    set -euxo pipefail

    dnf install -y python3.11 python3.11-pip docker git
    systemctl enable --now docker
    usermod -aG docker ec2-user

    python3.11 -m pip install --upgrade pip
    python3.11 -m pip install "ray[default]==${var.ray_version}" boto3 structlog

    # Wait for head to be reachable
    until nc -z ${aws_instance.head.private_ip} 6379; do
      echo "Waiting for Ray head..."
      sleep 5
    done

    cat > /usr/local/bin/start-ray-worker.sh <<SCRIPT
    #!/bin/bash
    ray start \
      --address=${aws_instance.head.private_ip}:6379 \
      --num-cpus=$(nproc) \
      --block
    SCRIPT
    chmod +x /usr/local/bin/start-ray-worker.sh

    cat > /etc/systemd/system/ray-worker.service <<'SVC'
    [Unit]
    Description=Ray Worker Node
    After=network.target

    [Service]
    User=ec2-user
    ExecStart=/usr/local/bin/start-ray-worker.sh
    Restart=on-failure
    RestartSec=10

    [Install]
    WantedBy=multi-user.target
    SVC

    systemctl daemon-reload
    systemctl enable --now ray-worker
  EOF
}

# ---------------------------------------------------------------------------
# Head node EC2 instance
# ---------------------------------------------------------------------------

resource "aws_instance" "head" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.head_instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.ray_head.id]
  iam_instance_profile   = aws_iam_instance_profile.ray_node.name
  key_name               = var.ssh_key_name != "" ? var.ssh_key_name : null
  user_data              = local.head_userdata

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  tags = merge(var.tags, { Name = local.head_name, "ray:role" = "head" })
}

# ---------------------------------------------------------------------------
# Worker Auto Scaling Group (Spot)
# ---------------------------------------------------------------------------

resource "aws_launch_template" "worker" {
  name_prefix   = "${local.worker_name}-"
  image_id      = data.aws_ami.al2023.id
  instance_type = var.worker_instance_type
  key_name      = var.ssh_key_name != "" ? var.ssh_key_name : null
  user_data     = base64encode(local.worker_userdata)

  iam_instance_profile {
    name = aws_iam_instance_profile.ray_node.name
  }

  network_interfaces {
    associate_public_ip_address = true
    security_groups             = [aws_security_group.ray_worker.id]
  }

  instance_market_options {
    market_type = "spot"
    spot_options {
      spot_instance_type             = "one-time"
      instance_interruption_behavior = "terminate"
    }
  }

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size = 30
      volume_type = "gp3"
    }
  }

  tag_specifications {
    resource_type = "instance"
    tags          = merge(var.tags, { Name = local.worker_name, "ray:role" = "worker" })
  }
}

resource "aws_autoscaling_group" "workers" {
  name                = "${local.worker_name}-asg"
  desired_capacity    = var.worker_count
  min_size            = 0
  max_size            = var.worker_count * 2
  vpc_zone_identifier = [var.subnet_id]

  launch_template {
    id      = aws_launch_template.worker.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = local.worker_name
    propagate_at_launch = true
  }

  lifecycle {
    create_before_destroy = true
  }
}
