###############################################################################
# GitHub Actions OIDC — federated identity for CI/CD
#
# Lets GitHub Actions exchange a short-lived OIDC token for temporary AWS
# credentials via STS AssumeRoleWithWebIdentity — no static IAM keys needed.
#
# How it works:
#   1. GitHub Actions runner issues a signed OIDC JWT for the workflow run
#   2. aws-actions/configure-aws-credentials exchanges it with STS
#   3. STS validates the JWT against token.actions.githubusercontent.com and
#      returns short-lived credentials scoped to this role
#   4. The role can push images to ECR — nothing else
###############################################################################

# ---------------------------------------------------------------------------
# OIDC identity provider — tells AWS to trust GitHub's token issuer
# ---------------------------------------------------------------------------

data "tls_certificate" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github.certificates[0].sha1_fingerprint]
  tags            = var.tags
}

# ---------------------------------------------------------------------------
# IAM role — assumed by GitHub Actions when a workflow runs on main
# ---------------------------------------------------------------------------

resource "aws_iam_role" "github_actions" {
  name        = "${var.name}-github-actions"
  description = "Assumed by GitHub Actions via OIDC to push images to ECR"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = [
            for branch in var.allowed_branches :
            "repo:${var.github_repo}:ref:refs/heads/${branch}"
          ]
        }
      }
    }]
  })

  tags = var.tags
}

# ---------------------------------------------------------------------------
# Managed policy — ECR push permissions via AWS-managed policy
# ---------------------------------------------------------------------------

resource "aws_iam_role_policy_attachment" "ecr_power_user" {
  role       = aws_iam_role.github_actions.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser"
}
