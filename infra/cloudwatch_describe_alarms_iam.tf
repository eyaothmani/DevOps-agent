resource "aws_iam_role_policy" "lambda_cloudwatch_describe_alarms" {
  name = "lambda-cloudwatch-describe-alarms"
  role = aws_iam_role.lambda_exec_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "cloudwatch:DescribeAlarms"
        Resource = "*"
      }
    ]
  })
}
