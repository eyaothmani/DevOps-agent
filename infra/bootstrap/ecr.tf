# infra/bootstrap/ecr.tf
resource "aws_ecr_repository" "dashboard_api" {
  name                 = "agent-devops-dashboard-api"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Project = "agent-devops-autonome"
    Epic    = "epic-6"
  }
}

resource "aws_ecr_lifecycle_policy" "dashboard_api_cleanup" {
  repository = aws_ecr_repository.dashboard_api.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Garder seulement les 10 dernières images (coût)"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

output "ecr_repository_url" {
  value = aws_ecr_repository.dashboard_api.repository_url
}
