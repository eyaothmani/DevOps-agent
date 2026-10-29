# infra/bootstrap/oidc.tf
# Permet à GitHub Actions de s'authentifier sur AWS sans clés IAM statiques.

variable "github_repo" {
  description = "Repo GitHub autorisé à assumer le rôle CI/CD, format 'org/repo'"
  type        = string
  default     = "eyaothmani/agent_devops" 
}

data "tls_certificate" "github" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github.certificates[0].sha1_fingerprint]

  tags = {
    Project = "agent-devops-autonome"
    Purpose = "github-actions-oidc"
  }

  lifecycle {
    ignore_changes = [thumbprint_list]
  }
}
data "aws_iam_policy_document" "github_actions_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Limite aux runs déclenchés depuis ce repo uniquement
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "github-actions-agent-devops-cd"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume.json

  tags = {
    Project = "agent-devops-autonome"
    Epic    = "epic-6"
  }
}

# Politique volontairement large pour boucler aujourd'hui (PoC/soutenance).
# À resserrer après la soutenance : scoper par ARN de ressource plutôt que "*".
resource "aws_iam_role_policy" "github_actions_deploy" {
  name = "github-actions-terraform-deploy"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "TerraformFullAccessPoC"
        Effect = "Allow"
        Action = [
          "ec2:*", "rds:*", "elasticloadbalancing:*", "autoscaling:*",
          "lambda:*", "sns:*", "sqs:*", "dynamodb:*", "iam:*",
          "logs:*", "cloudwatch:*", "ssm:*", "secretsmanager:*",
          "scheduler:*", "s3:*", "ecr:*"
        ]
        Resource = "*"
      }
    ]
  })
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions.arn
}
