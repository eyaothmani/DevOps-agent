resource "aws_lambda_function" "timeout_checker" {
  function_name    = "agent-devops-timeout-checker"
  filename         = data.archive_file.agent_lambda_zip.output_path
  source_code_hash = data.archive_file.agent_lambda_zip.output_base64sha256
  handler          = "agent.timeout_checker.handler"
  runtime          = "python3.11"
  timeout          = 90          
  memory_size      = 256

  role = aws_iam_role.lambda_exec_role.arn

  environment {
    variables = {
      LOG_LEVEL         = "INFO"
      SLACK_WEBHOOK_URL = var.SLACK_WEBHOOK_URL
      SLACK_CHANNEL     = "#devops-alerts"
    }
  }

  tags = {
    Project = "agent-devops-autonome"
    Epic    = "epic-4"
  }
}

# ─────────────────────────────────────────────────────────────────
# Déclenchement planifié — EventBridge classique (aws_cloudwatch_event_rule)
# ─────────────────────────────────────────────────────────────────
resource "aws_cloudwatch_event_rule" "timeout_checker_schedule" {
  name                = "agent-devops-timeout-checker-schedule"
  description         = "Déclenche timeout_checker toutes les minutes (US 4.8)"
  schedule_expression = "rate(1 minute)"
}

resource "aws_cloudwatch_event_target" "timeout_checker_target" {
  rule      = aws_cloudwatch_event_rule.timeout_checker_schedule.name
  target_id = "timeout-checker-lambda"
  arn       = aws_lambda_function.timeout_checker.arn
}

resource "aws_lambda_permission" "allow_eventbridge_invoke" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.timeout_checker.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.timeout_checker_schedule.arn
}