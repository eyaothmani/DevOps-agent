

resource "null_resource" "build_lambda_package" {
  triggers = {
    requirements_hash = filesha256("${path.module}/../requirements-lambda.txt")
    agent_code_hash = sha256(join("", [
      for f in fileset("${path.module}/../agent", "**/*.py") :
      filesha256("${path.module}/../agent/${f}")
    ]))
  }

  provisioner "local-exec" {
    command = "python3 ${abspath("${path.module}/../build_lambda_package.py")}"
  }
}

resource "aws_sqs_queue" "alarm_ingestion_dlq" {
  name                      = "agent-devops-alarm-ingestion-dlq"
  message_retention_seconds = 14 * 24 * 60 * 60 # 14 jours, le max SQS

  tags = {
    Project = "agent-devops-autonome"
    Purpose = "lambda-dlq"
  }
}

resource "aws_iam_role_policy" "lambda_dlq_policy" {
  name = "lambda-alarm-ingestion-dlq"
  role = aws_iam_role.lambda_exec_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:SendMessage"]
      Resource = aws_sqs_queue.alarm_ingestion_dlq.arn
    }]
  })
}

data "archive_file" "agent_lambda_zip" {
  type        = "zip"
  output_path = "${path.module}/build/agent_lambda.zip"
  source_dir  = "${path.module}/../agent/package"

  depends_on = [null_resource.build_lambda_package]
}

resource "aws_lambda_function" "alarm_ingestion" {
  function_name    = "agent-devops-alarm-ingestion"
  filename         = data.archive_file.agent_lambda_zip.output_path
  source_code_hash = data.archive_file.agent_lambda_zip.output_base64sha256
  handler          = "agent.lambda_handler.handler"
  runtime          = "python3.11"
  timeout          = 120
  memory_size      = 256

  role = aws_iam_role.lambda_exec_role.arn

  dead_letter_config {
    target_arn = aws_sqs_queue.alarm_ingestion_dlq.arn
  }

  environment {
    variables = {
      LOG_LEVEL               = "INFO"
      LOG_GROUP               = "/aws/ec2/agent-devops/app"
      SLACK_WEBHOOK_URL       = var.SLACK_WEBHOOK_URL
      SLACK_CHANNEL           = "#devops-alerts"
      BEDROCK_MODEL_ID        = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
      BEDROCK_SONNET_MODEL_ID = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
    }
  }

  tags = {
    Project = "agent-devops-autonome"
    Epic    = "epic-2"
  }
}

resource "aws_lambda_function_event_invoke_config" "alarm_ingestion_invoke_config" {
  function_name          = aws_lambda_function.alarm_ingestion.function_name
  maximum_retry_attempts = 0
}

resource "aws_lambda_permission" "allow_sns_invoke" {
  statement_id  = "AllowExecutionFromSNS"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.alarm_ingestion.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.alerts.arn
}

resource "aws_iam_role_policy" "lambda_elbv2_target_health" {
  name = "lambda-elbv2-target-health"
  role = aws_iam_role.lambda_exec_role.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "elasticloadbalancing:DescribeTargetHealth",
          "elasticloadbalancing:DescribeTargetGroups",
          "elasticloadbalancing:DescribeTargetGroupAttributes"
        ],
        Resource = "*"
      }
    ]
  })
}
resource "aws_dynamodb_table" "graph_checkpoints" {
  name         = "agent-devops-graph-checkpoints"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = {
    Project = "agent-devops-autonome"
    Epic    = "epic-4"
  }
}