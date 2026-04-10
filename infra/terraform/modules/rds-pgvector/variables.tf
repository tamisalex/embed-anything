variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "allowed_security_group_ids" {
  description = "SG IDs that may connect on port 5432 (e.g. ECS task SG)"
  type        = list(string)
  default     = []
}

variable "instance_class" {
  description = "db.t4g.micro is free-tier eligible"
  type        = string
  default     = "db.t4g.micro"
}

variable "allocated_storage" {
  description = "Storage in GB (20 GB is free-tier eligible)"
  type        = number
  default     = 20
}

variable "db_name" {
  type    = string
  default = "embeddings"
}

variable "db_username" {
  type    = string
  default = "embedadmin"
}

variable "deletion_protection" {
  type    = bool
  default = false
}

variable "tags" {
  type    = map(string)
  default = {}
}
