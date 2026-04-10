output "role_arn" {
  description = "ARN of the IAM role to set as role-to-assume in aws-actions/configure-aws-credentials"
  value       = aws_iam_role.github_actions.arn
}

output "oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC identity provider"
  value       = aws_iam_openid_connect_provider.github.arn
}
