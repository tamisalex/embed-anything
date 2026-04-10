variable "name_prefix" {
  description = "ECR repository name prefix (e.g. 'embed-anything')"
  type        = string
}

variable "repository_names" {
  description = "List of repository names to create"
  type        = list(string)
  default     = ["embed-pipeline", "embed-api"]
}

variable "max_images" {
  description = "Maximum number of images to retain per repository"
  type        = number
  default     = 5
}

variable "tags" {
  type    = map(string)
  default = {}
}
