from __future__ import annotations

import os


class Settings:
    # --- AWS & Environnement ---
    AWS_REGION: str = os.getenv("AWS_REGION", "eu-north-1")
    ENV: str = os.getenv("ENV", "dev")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # --- Slack ---
    SLACK_WEBHOOK_URL: str | None = os.getenv("SLACK_WEBHOOK_URL")
    SLACK_CHANNEL: str = os.getenv("SLACK_CHANNEL", "#devops-alerts")
    SLACK_SIGNING_SECRET: str = os.getenv("SLACK_SIGNING_SECRET", "")

    # --- Logs & SSM (US 2.3 / US 3.1) ---
    LOG_LOOKBACK_SECONDS: int = int(
        os.getenv("LOG_LOOKBACK_SECONDS", str(30 * 60))
    )  # 30 min
    LOG_GROUP: str = os.getenv("LOG_GROUP", "/aws/ec2/agent-devops/app")
    LOG_FETCH_MAX_EVENTS: int = int(os.getenv("LOG_FETCH_MAX_EVENTS", "200"))

    SSM_TIMEOUT_SECONDS: int = int(os.getenv("SSM_TIMEOUT_SECONDS", "45"))
    SSM_COMMAND_TIMEOUT_SECONDS: int = int(
        os.getenv("SSM_COMMAND_TIMEOUT_SECONDS", "45")
    )
    SSM_POLL_GRACE_SECONDS: int = int(os.getenv("SSM_POLL_GRACE_SECONDS", "5"))
    SSM_POLL_INTERVAL_SECONDS: int = int(os.getenv("SSM_POLL_INTERVAL_SECONDS", "2"))

    # --- US 4.3 : KILL SWITCH (Critique pour la soutenance) ---
    # Si False, le graphe fait le diagnostic mais n'exécute AUCUNE action SSM
    AUTO_REMEDIATION_ENABLED: bool = (
        os.getenv("AUTO_REMEDIATION_ENABLED", "true").lower() == "true"
    )

    # --- US 4.1 : Seuil de confiance ---
    CONFIDENCE_THRESHOLD: int = int(os.getenv("CONFIDENCE_THRESHOLD", "85"))

    # --- US 4.4 : Verrou anti-flapping (Cooldown) ---
    IDEMPOTENCY_TTL_SECONDS: int = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "120"))
    ACTION_LOCKS_TABLE: str = os.getenv("ACTION_LOCKS_TABLE", "agent_action_locks")

    # --- Modèles Bedrock (US 4.5 : FinOps Routing) ---
    # Modèle par défaut (léger, peu cher) -> Haiku
    BEDROCK_MODEL_ID: str = os.getenv(
        "BEDROCK_MODEL_ID", "anthropic.claude-haiku-4-5-20251001-v1:0"
    )
    # Modèle expert (lourd, cher) -> Sonnet
    BEDROCK_SONNET_MODEL_ID: str = os.getenv(
        "BEDROCK_SONNET_MODEL_ID", "anthropic.claude-sonnet-4-5-20250929-v1:0"
    )

    NO_ACTION_CONFIRMATION_THRESHOLD: int = 95
    VALIDATION_TIMEOUT_MINUTES: int = 15
    PENDING_VALIDATIONS_TABLE: str = "agent-devops-pending-validations"
    # --- US 4.8 : table DynamoDB du checkpointer LangGraph (persistance de
    # l'état suspendu entre l'invocation initiale et la reprise post-Slack) ---
    CHECKPOINTS_TABLE: str = os.getenv(
        "CHECKPOINTS_TABLE", "agent-devops-graph-checkpoints"
    )
    # Si le score de confiance du Haiku est < à ce seuil, on escalade vers Sonnet
    ROUTING_ESCALATION_THRESHOLD: int = int(
        os.getenv("ROUTING_ESCALATION_THRESHOLD", "50")
    )
    LOG_WINDOW_BEFORE_SECONDS: int = 600  # 10 min avant l'alarme
    LOG_WINDOW_AFTER_SECONDS: int = 60  # 1 min après
    # --- Paramètres généraux Bedrock ---
    BEDROCK_MAX_TOKENS: int = int(os.getenv("BEDROCK_MAX_TOKENS", "1024"))
    BEDROCK_TEMPERATURE: float = float(os.getenv("BEDROCK_TEMPERATURE", "0.1"))
    BEDROCK_MAX_RETRIES: int = int(os.getenv("BEDROCK_MAX_RETRIES", "2"))

    # --- US 4.9 : LLM-as-Juge (Auto-évaluation) ---
    # Si laissé vide, le juge utilisera le même modèle que BEDROCK_MODEL_ID (Haiku)
    BEDROCK_JUDGE_MODEL_ID: str = os.getenv("BEDROCK_JUDGE_MODEL_ID", "")

    # --- Tables DynamoDB (US 2.4) ---
    AGENT_DECISIONS_TABLE: str = os.getenv("AGENT_DECISIONS_TABLE", "agent_decisions")
    # Rétention de la table d'audit agent_decisions (US 5.2 a besoin de
    # l'historique pour les métriques, mais une table jamais purgée grossit
    # indéfiniment en PAY_PER_REQUEST — contraire à la contrainte "aucun
    # coût AWS additionnel"). 90 jours couvre largement une campagne de
    # tests + soutenance ; ajustable sans redéploiement de code.
    AGENT_DECISIONS_RETENTION_DAYS: int = int(
        os.getenv("AGENT_DECISIONS_RETENTION_DAYS", "90")
    )

    @property
    def effective_judge_model_id(self) -> str:
        """Retourne l'ID du modèle juge. Si non défini, utilise le modèle principal (Haiku)."""
        return self.BEDROCK_JUDGE_MODEL_ID or self.BEDROCK_MODEL_ID


# Instance unique des settings (Singleton)
settings = Settings()
