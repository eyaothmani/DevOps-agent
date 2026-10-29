
resource "aws_lambda_function" "resume_handler" {
  function_name    = "agent-devops-resume-handler"
  filename         = data.archive_file.agent_lambda_zip.output_path
  source_code_hash = data.archive_file.agent_lambda_zip.output_base64sha256
  handler          = "agent.resume_handler.handler"
  runtime          = "python3.11"
  timeout          = 90
  memory_size      = 256

  role = aws_iam_role.lambda_exec_role.arn

  environment {
    variables = {
      LOG_LEVEL             = "INFO"
      SLACK_SIGNING_SECRET  = var.SLACK_SIGNING_SECRET
      SLACK_WEBHOOK_URL     = var.SLACK_WEBHOOK_URL
      SLACK_CHANNEL         = "#devops-alerts"
    }
  }

  tags = {
    Project = "agent-devops-autonome"
    Epic    = "epic-4"
  }
}
resource "aws_iam_role_policy" "lambda_self_invoke" {
  name = "lambda-self-invoke-async"
  role = aws_iam_role.lambda_exec_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.resume_handler.arn
      }
    ]
  })
}
# ─────────────────────────────────────────────────────────────
# API Gateway HTTP API — expose resume_handler à Slack
# ─────────────────────────────────────────────────────────────
resource "aws_apigatewayv2_api" "slack_interactivity" {
  name          = "agent-devops-slack-interactivity"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "resume_handler_integration" {
  api_id                 = aws_apigatewayv2_api.slack_interactivity.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.resume_handler.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "slack_route" {
  api_id    = aws_apigatewayv2_api.slack_interactivity.id
  route_key = "POST /slack/interactivity"
  target    = "integrations/${aws_apigatewayv2_integration.resume_handler_integration.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.slack_interactivity.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "allow_apigw_invoke" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.resume_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.slack_interactivity.execution_arn}/*/*"
}
output "slack_interactivity_url" {
  value = "${trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")}/slack/interactivity"
}
resource "aws_iam_role_policy" "lambda_dynamodb_pending_validations" {
  name = "lambda-dynamodb-pending-validations"
  role = aws_iam_role.lambda_exec_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
          "dynamodb:Scan",
          "dynamodb:Query"
        ]
        Resource = "arn:aws:dynamodb:eu-north-1:014498640042:table/agent-devops-pending-validations"
      }
    ]
  })
}