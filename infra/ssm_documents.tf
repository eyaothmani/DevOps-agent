resource "aws_ssm_document" "rollback_deployment" {
  name          = "Custom-RollbackDeployment"
  document_type = "Command"
  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Rollback vers la version précédente du déploiement applicatif"
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "rollback"
      inputs = {
        runCommand = [
          "sudo systemctl stop myapp",
          "sudo cp /opt/myapp/releases/previous/* /opt/myapp/current/",
          "sudo systemctl start myapp"
        ]
      }
    }]
  })
}
resource "aws_ssm_document" "scale_out_asg" {
  name            = "Custom-ScaleOutASG"
  document_type   = "Automation"
  document_format = "JSON"
  content = jsonencode({
    schemaVersion = "0.3"
    description   = "Augmente la capacite desiree de l'Auto Scaling Group"
    assumeRole    = aws_iam_role.automation_role.arn
    parameters = {
      AutoScalingGroupName = {
        type    = "String"
        default = aws_autoscaling_group.asg.name
      }
      DesiredCapacity = {
        type    = "Integer"
        default = 3
      }
    }
    mainSteps = [{
      name   = "scale_out"
      action = "aws:executeAwsApi"
      inputs = {
        Service              = "autoscaling"
        Api                  = "SetDesiredCapacity"
        AutoScalingGroupName = "{{ AutoScalingGroupName }}"
        DesiredCapacity      = "{{ DesiredCapacity }}"
      }
    }]
  })
}