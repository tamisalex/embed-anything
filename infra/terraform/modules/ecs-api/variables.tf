variable "name" { type = string }
variable "vpc_id" { type = string }
variable "public_subnet_ids" { type = list(string) }
variable "aws_region" { type = string }

variable "container_image" {
  description = "ECR image URI for embed-api"
  type        = string
}

variable "task_cpu" {
  description = "Fargate task vCPU units (256 = 0.25 vCPU)"
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "Fargate task memory in MB"
  type        = number
  default     = 1024
}

variable "desired_count" {
  description = "Number of running API tasks"
  type        = number
  default     = 1
}

variable "enable_alb" {
  description = "Put an ALB in front of the API task. Set false for personal/dev use — the task gets a public IP directly and is locked to allowed_cidr."
  type        = bool
  default     = false
}

variable "allowed_cidr" {
  description = "CIDRs allowed to reach port 8080 directly when enable_alb = false. Defaults to your IP only — change to your actual IP."
  type        = list(string)
  default     = ["0.0.0.0/0"]
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
  default = "pinecone"
}

variable "store_dimension" {
  type    = number
  default = 512
}

variable "pinecone_api_key_secret_arn" {
  description = "Secrets Manager ARN for the Pinecone API key — injected by ECS at startup"
  type        = string
}

variable "pinecone_host" {
  description = "Pinecone index host (e.g. embed-anything-xxxxx.svc.aped-4627-b74a.pinecone.io)"
  type        = string
}

variable "secrets_arns" {
  type    = list(string)
  default = []
}

variable "tags" {
  type    = map(string)
  default = {}
}
