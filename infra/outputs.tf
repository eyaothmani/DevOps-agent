output "vpc_id" {
  value = aws_vpc.main.id
}

output "ec2_subnet" {
  value = aws_subnet.public_subnet.id
}

output "rds_endpoint" {
  value = aws_db_instance.db.endpoint
}
output "alb_dns_name" {
  value = aws_lb.main.dns_name
}

output "sns_topic_arn" {
  value = aws_sns_topic.alerts.arn
}
output "sns_alarm_topic_arn" {
  description = "ARN du topic SNS utilisé par les alarmes CloudWatch"
  value       = aws_sns_topic.alerts.arn # ⬅️ changé
}

output "lambda_ingestion_function_name" {
  description = "Nom de la Lambda d'ingestion des alertes"
  value       = aws_lambda_function.alarm_ingestion.function_name
}
