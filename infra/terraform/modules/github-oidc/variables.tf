variable "name" {
  description = "Resource name prefix"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository in owner/repo format (e.g. tamisalex/embed-anything)"
  type        = string
}

variable "allowed_branches" {
  description = "Branches that are allowed to assume the role"
  type        = list(string)
  default     = ["main"]
}

variable "tags" {
  type    = map(string)
  default = {}
}
