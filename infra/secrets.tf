# ---------------------------------------------------------------------------
# Mot de passe RDS généré automatiquement — jamais en clair dans le code
# ni dans le state (Terraform masque les valeurs des ressources "random"
# et "secretsmanager" marquées sensitives dans les logs/plan, mais le state
# reste la source de vérité : voir .gitignore, il ne doit JAMAIS être commité).
# ---------------------------------------------------------------------------

resource "random_password" "rds_master" {
  length           = 24
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
  min_upper        = 2
  min_lower        = 2
  min_numeric      = 2
  min_special      = 2
}

resource "aws_secretsmanager_secret" "rds_master" {
  name        = "agent-devops/rds/master-credentials"
  description = "Identifiants RDS eya-mydb generes par Terraform (US 1.1)"

  # PoC jetable, détruit/recréé en boucle (US 6.4) — pas de fenêtre de
  # récupération de 30 jours par défaut, sinon un destroy suivi d'un apply
  # échoue tant que le secret reste "scheduled for deletion".
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "rds_master" {
  secret_id = aws_secretsmanager_secret.rds_master.id
  secret_string = jsonencode({
    username = "admin"
    password = random_password.rds_master.result
    engine   = "mysql"
    host     = aws_db_instance.db.address
    port     = 3306
    dbname   = "appdb"
  })
}