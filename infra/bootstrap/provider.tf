provider "aws" {
  region = "eu-north-1"

  # US 6.4 : tag automatique de TOUTE ressource créée par ce provider.
  # Se combine avec les tags déjà définis au niveau des ressources (ils ne
  # sont pas écrasés) — permet le suivi des coûts par projet dans Cost
  # Explorer sans devoir modifier chaque bloc `tags = {}` existant.
  default_tags {
    tags = {
      Project     = "agent-devops-autonome"
      Environment = var.environment
      Owner       = var.owner
    }
  }
}
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}