

resource "aws_sns_topic_subscription" "email_alert" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = "othmanieya00@gmail.com"
}

# --- Alarme 1 : CPU > 80% pendant 5 minutes ---
resource "aws_cloudwatch_metric_alarm" "cpu_high" {
  alarm_name          = "eya-asg-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "CPU moyen de l'ASG > 80% pendant 5 minutes"
  treat_missing_data  = "notBreaching"

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.asg.name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Name = "eya-cpu-alarm" }
}

# --- Alarme 2 : taux d'erreur 5xx > 5% (via Metric Math) ---
resource "aws_cloudwatch_metric_alarm" "error_5xx_rate_high" {
  alarm_name          = "eya-alb-5xx-rate-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 5
  alarm_description   = "Taux d'erreur 5xx > 5% sur l'ALB pendant 5 minutes"
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "rate"
    expression  = "(errors / requests) * 100"
    label       = "Taux erreur 5xx (%)"
    return_data = true
  }

  metric_query {
    id = "errors"
    metric {
      metric_name = "HTTPCode_Target_5XX_Count"
      namespace   = "AWS/ApplicationELB"
      period      = 300
      stat        = "Sum"
      dimensions = {
        LoadBalancer = aws_lb.main.arn_suffix
      }
    }
  }

  metric_query {
    id = "requests"
    metric {
      metric_name = "RequestCount"
      namespace   = "AWS/ApplicationELB"
      period      = 300
      stat        = "Sum"
      dimensions = {
        LoadBalancer = aws_lb.main.arn_suffix
      }
    }
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Name = "eya-5xx-alarm" }
}

# ─── Log Group pour les logs applicatifs EC2 ────────────────────────────────
# NOTE SÉCURITÉ : CloudWatch Logs est chiffré au repos par défaut par AWS.
# Pas de CMK dédiée ajoutée ici (coût KMS ~$1/mois non justifié pour un PoC).
resource "aws_cloudwatch_log_group" "ec2_app_logs" {
  name              = "/aws/ec2/agent-devops/app"
  retention_in_days = 7

  tags = {
    Project = "agent-devops-autonome"
    Purpose = "logs-applicatifs-diagnostic-ia"
  }
}

resource "aws_cloudwatch_metric_alarm" "service_down" {
  alarm_name          = "eya-servicedown"
  comparison_operator = "LessThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "HealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Minimum"
  threshold           = 0
  alarm_description   = "Aucune instance saine derrière l'ALB (service down)"
  treat_missing_data  = "breaching"

  dimensions = {
    TargetGroup  = aws_lb_target_group.ec2_tg.arn_suffix
    LoadBalancer = aws_lb.main.arn_suffix
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Name = "eya-servicedown-alarm" }
}