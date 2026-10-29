data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

resource "aws_iam_role" "lambda_exec_role" {
  name = "agent-devops-lambda-exec-role"

  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# Logs CloudWatch pour la Lambda (debug, traçabilité)
resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Principe du moindre privilège (cf. Bug 2 anticipé) :
# lecture seule des logs CloudWatch, nécessaire pour l'US 2.2 (RCA)
resource "aws_iam_role_policy" "lambda_cloudwatch_logs_read" {
  name = "lambda-cloudwatch-logs-read"
  role = aws_iam_role.lambda_exec_role.id

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:GetLogEvents",
          "logs:FilterLogEvents",
          "logs:DescribeLogStreams"
        ]
        Resource = [
         "arn:aws:logs:eu-north-1:014498640042:log-group:/aws/lambda/*:*",
          "arn:aws:logs:eu-north-1:014498640042:log-group:/agent-devops/*:*",
          "arn:aws:logs:eu-north-1:014498640042:log-group:/aws/ec2/agent-devops/app:*"
        ]
      }
    ]
  })
}

# Permission d'invoquer Bedrock pour l'analyse RCA (US 2.2)
resource "aws_iam_role_policy" "lambda_bedrock_invoke" {
  name = "lambda-bedrock-invoke"
  role = aws_iam_role.lambda_exec_role.id

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]
      Resource = [
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
        "arn:aws:bedrock:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:inference-profile/eu.anthropic.claude-haiku-4-5-20251001-v1:0",
        "arn:aws:bedrock:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:inference-profile/eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
      ]
    }]
  })
}
resource "aws_iam_role_policy" "lambda_autoscaling_policy" {
  name = "lambda-autoscaling-read"
  role = aws_iam_role.lambda_exec_role.id

  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        # Describe* : pas de scoping resource-level possible (limitation API AWS)
        Effect = "Allow",
        Action = [
          "autoscaling:DescribeAutoScalingGroups",
          "autoscaling:DescribeAutoScalingInstances"
        ],
        Resource = "*"
      }
    ]
  })
}
resource "aws_iam_role_policy" "lambda_dynamodb_policy" {
  name = "lambda-dynamodb-agent-decisions"
  role = aws_iam_role.lambda_exec_role.id

  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:Query"
        ],
        Resource = aws_dynamodb_table.agent_decisions.arn
      }
    ]
  })
}
# Permission d'écrire/lire/supprimer les verrous d'action, nécessaire
# pour que l'agent puisse réellement exécuter ScaleOut (fail-open) au
# lieu de sauter l'action en fail-closed (AccessDenied).
resource "aws_iam_role_policy" "lambda_dynamodb_locks_policy" {
  name   = "lambda-dynamodb-agent-action-locks"
  role   = aws_iam_role.lambda_exec_role.id
  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:DeleteItem"
        ],
        Resource = aws_dynamodb_table.agent_action_locks.arn
      }
    ]
  })
}
resource "aws_iam_role_policy" "lambda_ssm_policy" {
  name = "lambda-ssm-remediation"
  role = aws_iam_role.lambda_exec_role.id

  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        # ssm:SendCommand supporte les permissions au niveau ressource :
        # restreint aux 3 documents effectivement whitelistés dans
        # agent/graph/whitelist.py (ACTION_TO_SSM_DOCUMENT), plutôt que
        # tout document SSM du compte. Corrige la faille identifiée lors
        # de l'audit IAM du 27/07/2026 (Resource "*" sur SendCommand).
        Effect   = "Allow",
        Action   = ["ssm:SendCommand"],
        Resource = [
          "arn:aws:ssm:${data.aws_region.current.region}::document/AWS-RunShellScript",
          "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:document/Custom-ScaleOutASG",
          "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:document/Custom-RollbackDeployment",
          "arn:aws:ec2:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:instance/*"
        ]
      },
      {
        # ssm:GetCommandInvocation et ssm:DescribeInstanceInformation ne
        # supportent PAS les permissions au niveau ressource (limitation
        # documentée de l'API SSM, pas un relâchement de notre part) :
        # Resource reste "*" spécifiquement pour ces deux actions.
        Effect = "Allow",
        Action = [
          "ssm:GetCommandInvocation",
          "ssm:DescribeInstanceInformation"
        ],
        Resource = "*"
      }
    ]
  })
}
resource "aws_iam_role_policy" "lambda_ssm_parameter_policy" {
  name = "lambda-ssm-parameter-store"
  role = aws_iam_role.lambda_exec_role.id

  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = ["ssm:GetParameter"],
        # Scope au namespace du projet uniquement (ex. AUTO_REMEDIATION_ENABLED, US 4.3)
        Resource = "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter/agent-devops/*"
      }
    ]
  })
}
resource "aws_iam_role" "automation_role" {
  name               = "agent-devops-automation-role"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ssm.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "automation_autoscaling" {
  name   = "automation-autoscaling-set-capacity"
  role   = aws_iam_role.automation_role.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [
      {
        # SetDesiredCapacity supporte le scoping resource-level
        Effect   = "Allow"
        Action   = ["autoscaling:SetDesiredCapacity"]
        Resource = "arn:aws:autoscaling:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:autoScalingGroup:*:autoScalingGroupName/${aws_autoscaling_group.asg.name}"
      },
      {
        # DescribeAutoScalingGroups ne supporte pas le scoping resource-level
        # (action de type Describe*, limitation API AWS documentée)
        Effect   = "Allow"
        Action   = ["autoscaling:DescribeAutoScalingGroups"]
        Resource = "*"
      }
    ]
  })
}
# La Lambda/agent doit pouvoir lancer l'automation et lui passer ce rôle
resource "aws_iam_role_policy" "lambda_ssm_automation_policy" {
  name   = "lambda-ssm-automation-start"
  role   = aws_iam_role.lambda_exec_role.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [
      {
        # StartAutomationExecution supporte le scoping resource-level : restreint
        # aux 2 documents d'automation du projet
        Effect   = "Allow"
        Action   = ["ssm:StartAutomationExecution"]
        Resource = [
          "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:automation-definition/Custom-ScaleOutASG:*",
          "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:automation-definition/Custom-RollbackDeployment:*"
        ]
      },
      {
        # ssm:GetAutomationExecution / StopAutomationExecution nécessitent un
        # execution-id généré à l'exécution, non connu à l'avance : ces actions
        # ne supportent pas le scoping resource-level (limitation API documentée).
        Effect   = "Allow"
        Action   = ["ssm:GetAutomationExecution", "ssm:StopAutomationExecution"]
        Resource = "*"
      },
      {
        Effect    = "Allow"
        Action    = "iam:PassRole"
        Resource  = aws_iam_role.automation_role.arn
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "ssm.amazonaws.com"
          }
        }
      }
    ]
  })
}
# Permission d'accès au checkpointer LangGraph (US 4.8 — human-in-the-loop
# natif via interrupt()) : persistance/reprise de l'état suspendu du graphe.
resource "aws_iam_role_policy" "lambda_dynamodb_graph_checkpoints" {
  name = "lambda-dynamodb-graph-checkpoints"
  role = aws_iam_role.lambda_exec_role.id

  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ],
        Resource = [
          aws_dynamodb_table.graph_checkpoints.arn,
          "${aws_dynamodb_table.graph_checkpoints.arn}/index/*"
        ]
      }
    ]
  })
}