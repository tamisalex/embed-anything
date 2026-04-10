variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_id" {
  description = "Single public subnet for all Ray nodes (head + workers in same AZ = no cross-AZ data transfer costs)"
  type        = string
}

variable "head_instance_type" {
  description = "EC2 instance type for the Ray head node"
  type        = string
  default     = "t3.medium"
}

variable "worker_instance_type" {
  description = "EC2 instance type for Ray workers"
  type        = string
  default     = "t3.small"
}

variable "worker_count" {
  description = "Desired number of worker nodes"
  type        = number
  default     = 2
}

variable "ray_version" {
  description = "Ray version to install (pip)"
  type        = string
  default     = "2.20.0"
}

variable "ssh_key_name" {
  description = "EC2 key pair name for SSH access (leave empty to disable)"
  type        = string
  default     = ""
}

variable "dashboard_cidr_allowlist" {
  description = "CIDRs allowed to reach the Ray dashboard (port 8265) and SSH"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "data_bucket" {
  description = "S3 bucket name that Ray nodes need read/write access to"
  type        = string
}

variable "secrets_arns" {
  description = "Secrets Manager ARNs the Ray nodes may read (e.g. DB password)"
  type        = list(string)
  default     = []
}

variable "tags" {
  type    = map(string)
  default = {}
}
