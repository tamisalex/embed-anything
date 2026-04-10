variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "env" {
  type    = string
  default = "dev"
}

variable "data_bucket" {
  description = "S3 bucket containing source images"
  type        = string
}

variable "athena_results_bucket" {
  description = "S3 bucket for Athena query output (can be the same as data_bucket)"
  type        = string
}

variable "provider_type" {
  description = "Embedding provider: clip | sentence_transformers | bedrock | openai"
  type        = string
  default     = "clip"
}

variable "provider_model_name" {
  type    = string
  default = "ViT-B-32"
}

variable "provider_pretrained" {
  type    = string
  default = "openai"
}

variable "embedding_dimension" {
  type    = number
  default = 512
}

variable "my_ip_cidr" {
  description = "Your IP in CIDR notation to lock API access (e.g. '1.2.3.4/32'). Find it with: curl ifconfig.me"
  type        = list(string)
  default     = ["0.0.0.0/0"]  # tighten this in terraform.tfvars
}
