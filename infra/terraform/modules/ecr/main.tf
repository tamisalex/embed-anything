###############################################################################
# ECR repositories — one per service
# Free tier: 500 MB/month private storage
###############################################################################

resource "aws_ecr_repository" "repos" {
  for_each = toset(var.repository_names)

  name                 = "${var.name_prefix}/${each.key}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = var.tags
}

# Lifecycle policy: keep only the last N images to stay within free tier
resource "aws_ecr_lifecycle_policy" "cleanup" {
  for_each   = aws_ecr_repository.repos
  repository = each.value.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last ${var.max_images} images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.max_images
      }
      action = { type = "expire" }
    }]
  })
}
