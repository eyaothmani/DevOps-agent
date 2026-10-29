# ssm_kill_switch.tf
# Kill switch de l'agent — mécanisme d'arrêt d'urgence, vérifié en tout
# début du graphe (avant même le node Diagnostic) pour ne pas gaspiller
# d'appel Bedrock si l'agent est désactivé.
#
# Valeurs : "ENABLED" (défaut, agent actif) / "DISABLED" (arrêt).
# Fail-closed volontaire côté code : si ce paramètre est illisible pour
# une raison quelconque (panne SSM, permission), l'agent se comporte
# comme si le kill switch était engagé (DISABLED) — cohérent avec la
# philosophie déjà adoptée pour le verrou d'idempotence.
resource "aws_ssm_parameter" "agent_kill_switch" {
  name        = "/agent-devops/kill_switch"
  description = "Arrêt d'urgence de l'agent DevOps autonome. ENABLED = actif, DISABLED = toute action est bloquée avant même le diagnostic."
  type        = "String"
  value       = "ENABLED"

  # lifecycle.ignore_changes évite que Terraform n'écrase la valeur si
  # un opérateur bascule le kill switch manuellement en urgence via la
  # console/CLI — Terraform ne doit pas remettre "ENABLED" au prochain
  # apply et annuler un arrêt d'urgence en cours.
  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Project = "agent-devops-autonome"
    Purpose = "kill-switch"
  }
}

output "agent_kill_switch_parameter_name" {
  value = aws_ssm_parameter.agent_kill_switch.name
}
