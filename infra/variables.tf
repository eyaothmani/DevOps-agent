variable "SLACK_WEBHOOK_URL" {
  description = "URL du webhook Slack Incoming Webhook pour le canal #devops-alerts"
  type        = string
  sensitive   = true
}
variable "SLACK_SIGNING_SECRET" {
  description = "Signing secret Slack pour vérifier l'authenticité des requêtes interactives (boutons Approuver/Rejeter)"
  type        = string
  sensitive   = true
}

variable "environment" {
  description = "Nom de l'environnement (tag Environment, US 6.4) — permet de filtrer les coûts dans Cost Explorer"
  type        = string
  default     = "stage"
}

variable "owner" {
  description = "Propriétaire du projet (tag Owner, US 6.4)"
  type        = string
  default     = "eya-devops-stage"
}

variable "budget_alert_email" {
  description = "Adresse e-mail recevant l'alerte de dépassement de budget AWS (US 6.4)"
  type        = string
}

variable "monthly_budget_usd" {
  description = "Plafond mensuel en USD pour l'alerte AWS Budgets (filet de sécurité FinOps, US 6.4)"
  type        = string
  default     = "10"
}
variable "enable_aws_budget" {
  description = "Active aws_budgets_budget (nécessite budgets:ModifyBudget) — false par défaut, compte partagé sans permission Budgets"
  type        = bool
  default     = false
}