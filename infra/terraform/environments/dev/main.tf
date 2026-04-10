###############################################################################
# Dev environment — wires all modules together
###############################################################################

terraform {
  required_version = ">= 1.7, != 1.5.7"  # use OpenTofu: `tofu init/plan/apply`

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  # Uncomment to use S3 remote state
  # backend "s3" {
  #   bucket = "your-tfstate-bucket"
  #   key    = "embed-anything/dev/terraform.tfstate"
  #   region = "us-east-1"
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

locals {
  name = "ea-${var.env}"
  common_tags = {
    Project     = "embed-anything"
    Environment = var.env
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------

module "networking" {
  source = "../../modules/networking"

  name               = local.name
  vpc_cidr           = "10.0.0.0/16"
  az_count           = 2
  enable_nat_gateway = false  # keep costs down; all nodes in public subnets
  tags               = local.common_tags
}

# ---------------------------------------------------------------------------
# ECR repositories
# ---------------------------------------------------------------------------

module "ecr" {
  source = "../../modules/ecr"

  name_prefix      = "embed-anything"
  repository_names = ["embed-pipeline", "embed-api"]
  tags             = local.common_tags
}

# ---------------------------------------------------------------------------
# RDS pgvector
# ---------------------------------------------------------------------------

module "rds" {
  source = "../../modules/rds-pgvector"

  name       = local.name
  vpc_id     = module.networking.vpc_id
  subnet_ids = module.networking.public_subnet_ids

  # Allow pipeline task and API task to connect
  allowed_security_group_ids = [
    module.pipeline_task.task_security_group_id,
    module.ecs_api.task_security_group_id,
  ]

  instance_class    = "db.t4g.micro"
  allocated_storage = 20
  deletion_protection = false

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# Pipeline ECS task (on-demand — zero cost when idle)
# ---------------------------------------------------------------------------

module "pipeline_task" {
  source = "../../modules/pipeline-task"

  name       = local.name
  vpc_id     = module.networking.vpc_id
  aws_region = var.aws_region

  container_image       = "${module.ecr.repository_urls["embed-pipeline"]}:latest"
  data_bucket           = var.data_bucket
  athena_results_bucket = var.athena_results_bucket

  rds_security_group_id = module.rds.security_group_id
  enable_rds_access     = true
  secrets_arns          = [module.rds.password_secret_arn]

  provider_type       = var.provider_type
  provider_model_name = var.provider_model_name
  provider_pretrained = var.provider_pretrained
  store_type          = "pgvector"
  store_dimension     = var.embedding_dimension
  store_dsn           = "postgresql://${module.rds.db_username}:PLACEHOLDER@${module.rds.endpoint}/${module.rds.db_name}"

  task_cpu    = 2048  # 2 vCPU — comfortable for CLIP + Ray local
  task_memory = 8192  # 8 GB

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# ECS API service
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# GitHub Actions OIDC — federated identity for CI/CD (ECR push)
# ---------------------------------------------------------------------------

module "github_oidc" {
  source = "../../modules/github-oidc"

  name                = local.name
  github_repo         = "tamisalex/embed-anything"
  ecr_repository_arns = values(module.ecr.repository_arns)
  tags                = local.common_tags
}

# ---------------------------------------------------------------------------
# Prefect OIDC — federated identity for Prefect Managed work pool
# ---------------------------------------------------------------------------

module "prefect_oidc" {
  source = "../../modules/prefect-oidc"

  name                 = local.name
  prefect_account_id   = var.prefect_account_id
  pipeline_cluster_arn = module.pipeline_task.cluster_arn
  ecs_role_arns = [
    module.pipeline_task.task_role_arn,
    module.pipeline_task.execution_role_arn,
  ]
  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# ECS API service
# ---------------------------------------------------------------------------

module "ecs_api" {
  source = "../../modules/ecs-api"

  name              = local.name
  vpc_id            = module.networking.vpc_id
  public_subnet_ids = module.networking.public_subnet_ids
  aws_region        = var.aws_region

  container_image = "${module.ecr.repository_urls["embed-api"]}:latest"

  provider_type        = var.provider_type
  provider_model_name  = var.provider_model_name
  provider_pretrained  = var.provider_pretrained
  store_type           = "pgvector"
  store_dimension      = var.embedding_dimension
  store_dsn     = "postgresql://${module.rds.db_username}:PLACEHOLDER@${module.rds.endpoint}/${module.rds.db_name}"

  secrets_arns  = [module.rds.password_secret_arn]
  desired_count = 1
  enable_alb    = false
  allowed_cidr  = var.my_ip_cidr

  tags = local.common_tags
}
