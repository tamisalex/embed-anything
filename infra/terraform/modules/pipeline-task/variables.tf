variable "name" { type = string }
variable "vpc_id" { type = string }
variable "aws_region" { type = string }

variable "container_image" {
  description = "ECR image URI for embed-pipeline"
  type        = string
}

variable "task_cpu" {
  description = "Fargate vCPU units. 2048 = 2 vCPU (min for 16 GB memory)"
  type        = number
  default     = 2048
}

variable "task_memory" {
  description = "Memory in MB. 8192 MB is comfortable for CLIP ViT-B-32 + Ray local"
  type        = number
  default     = 8192
}

variable "data_bucket" {
  description = "S3 bucket containing source images"
  type        = string
}

variable "athena_results_bucket" {
  description = "S3 bucket for Athena query output"
  type        = string
}

variable "rds_security_group_id" {
  description = "RDS security group ID to allow ingress from the pipeline task"
  type        = string
  default     = ""
}

variable "enable_rds_access" {
  description = "Set to true to create the ingress rule from the pipeline task to RDS. Must be a literal true/false, not derived from a resource attribute."
  type        = bool
  default     = false
}

variable "secrets_arns" {
  description = "Secrets Manager ARNs the task may read (e.g. DB password)"
  type        = list(string)
  default     = []
}

variable "provider_type" {
  type    = string
  default = "clip"
}

variable "provider_model_name" {
  type    = string
  default = "ViT-B-32"
}

variable "provider_pretrained" {
  type    = string
  default = "openai"
}

variable "store_type" {
  type    = string
  default = "pgvector"
}

variable "store_dimension" {
  type    = number
  default = 512
}

variable "store_dsn_secret_arn" {
  description = "Secrets Manager ARN for the full pgvector DSN — injected by ECS at startup"
  type        = string
}

variable "pinecone_api_key_secret_arn" {
  description = "Secrets Manager ARN for the Pinecone API key — injected by ECS at startup. Leave empty if not using Pinecone."
  type        = string
  default     = ""
}

variable "ray_num_actors" {
  description = "Number of parallel embedding actors in Ray local mode"
  type        = number
  default     = 4
}

variable "ray_batch_size" {
  description = "Items per batch passed to each actor"
  type        = number
  default     = 32
}

variable "tags" {
  type    = map(string)
  default = {}
}
