resource "aws_sns_topic" "alerts" {
  name = "eya-devops-alerts"
  tags = { Name = "eya-sns-alerts" }
}

# Abonnement : la Lambda d'ingestion écoute ce topic
resource "aws_sns_topic_subscription" "lambda_subscription" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.alarm_ingestion.arn
}