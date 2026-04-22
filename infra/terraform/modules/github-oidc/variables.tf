variable "name" {
  description = "Resource name prefix"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository in owner/repo format (e.g. tamisalex/embed-anything)"
  type        = string
}

variable "ecr_repository_arns" {
  description = "ARNs of the ECR repositories the role is allowed to push to"
  type        = list(string)
}

variable "tags" {
  type    = map(string)
  default = {}
}
