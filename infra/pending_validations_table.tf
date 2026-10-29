# ─────────────────────────────────────────────────────────────────
# Table DynamoDB — validations humaines en attente (US 4.8)
# Utilisée par register_pending_validation / try_claim_validation /
# clear_pending_validation / list_expired_validations
# (agent/pending_validations.py). N'existait pas encore : la policy
# IAM correspondante avait été créée sans la table elle-même,
# causant un ResourceNotFoundException sur DeleteItem.
# ─────────────────────────────────────────────────────────────────
resource "aws_dynamodb_table" "pending_validations" {
  name         = "agent-devops-pending-validations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "incident_id"

  attribute {
    name = "incident_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Project = "agent-devops-autonome"
    Epic    = "epic-4"
  }
}
