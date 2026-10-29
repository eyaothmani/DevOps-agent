# ─────────────────────────────────────────────────────────────────
# Tables DynamoDB — Epic 2 (US 2.4 : logging des décisions) et
# Epic 4 (US 4.4 : verrou anti-flapping / idempotence).
#
# NOTE DE CORRECTIF : ce fichier avait été écrasé par le contenu
# Python de agent/dynamo_logger.py (probablement un copier-coller
# malheureux entre les deux fichiers), ce qui faisait planter
# `terraform apply` avec des erreurs "Unsupported block type" sur
# `from`, `import`, `class`, etc. Terraform essayait d'interpréter
# du Python comme du HCL. Reconstruit ici à partir du code agent
# réel (agent/dynamo_logger.py, agent/idempotency_lock.py,
# agent/config.py) qui fait foi pour les noms de table et de clés.
# ─────────────────────────────────────────────────────────────────

# US 2.4 — Table d'audit des décisions de l'agent.
# Clé : incident_id (hash) + node_timestamp (range), un item par
# contribution de node (Diagnostic / Décision / Communication) pour
# un même incident. Le TTL sur "expires_at" correspond à l'attribut
# que agent/dynamo_logger.py écrit sur CHAQUE item
# (now + AGENT_DECISIONS_RETENTION_DAYS * 86400) : sans ce bloc TTL
# côté table, cet attribut est un no-op silencieux et la table
# grossit indéfiniment (contraire à la contrainte "aucun coût AWS
# additionnel").
resource "aws_dynamodb_table" "agent_decisions" {
  name         = "agent_decisions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "incident_id"
  range_key    = "node_timestamp"

  attribute {
    name = "incident_id"
    type = "S"
  }

  attribute {
    name = "node_timestamp"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = {
    Project = "agent-devops-autonome"
    Epic    = "epic-2"
  }
}

# US 4.4 — Verrou d'idempotence / anti-flapping par (resource_id,
# action_type). Clé : lock_key = "{resource_id}#{action_type}".
# agent/idempotency_lock.py écrit "expires_at" sur chaque verrou et
# s'appuie sur une ConditionExpression applicative pour le cooldown
# (pas sur le TTL DynamoDB, qui purge avec un délai de plusieurs
# heures et ne suffit donc pas à lui seul à garantir le cooldown).
# Le backlog (US 4.4, notes V6) indiquait ce TTL comme "à confirmer" :
# il est activé ici pour le nettoyage de fond, en complément — non en
# remplacement — de la vérification applicative.
resource "aws_dynamodb_table" "agent_action_locks" {
  name         = "agent_action_locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "lock_key"

  attribute {
    name = "lock_key"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = {
    Project = "agent-devops-autonome"
    Epic    = "epic-4"
  }
}
