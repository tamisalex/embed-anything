output "role_arn" {
  description = "ARN of the IAM role to configure in the Prefect AwsCredentials block"
  value       = aws_iam_role.prefect_runner.arn
}

output "oidc_provider_arn" {
  description = "ARN of the Prefect OIDC identity provider"
  value       = aws_iam_openid_connect_provider.prefect.arn
}
