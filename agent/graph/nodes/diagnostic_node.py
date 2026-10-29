from __future__ import annotations

import logging
from decimal import Decimal

from agent.bedrock_client import BedrockClient
from agent.config import settings
from agent.dynamo_logger import DynamoDecisionLogger
from agent.graph.state import AgentState
from agent.groundedness import compute_groundedness_score
from agent.log_fetcher import fetch_recent_logs, format_logs_for_prompt

logger = logging.getLogger(__name__)

NODE_NAME = "Diagnostic"

_bedrock_client = BedrockClient()
_decision_logger = DynamoDecisionLogger()


def diagnostic_node(agent_state: AgentState) -> dict:
    """Exécute le diagnostic complet et retourne l'état mis à jour."""
    state = agent_state["state"]
    alarm = state.alarm

    logger.info(
        "[%s] Démarrage du diagnostic pour incident_id=%s",
        NODE_NAME,
        state.incident_id,
    )

    # US 2.3 - étape 1 : récupération des logs récents
    logs = fetch_recent_logs(instance_id=alarm.instance_id, around_time=alarm.timestamp)
    state.logs = logs
    logs_text = format_logs_for_prompt(logs)

    # US 2.3 - étape 2 : premier appel Bedrock (modèle par défaut = Haiku, FinOps)
    rca_result = _bedrock_client.diagnose(alarm=alarm, logs_text=logs_text)

    # US 4.5 - routage FinOps : si la confiance du premier passage est trop
    # faible pour être exploitable, un second appel sur un modèle plus
    # capable (Sonnet) est déclenché, plutôt que d'utiliser Sonnet par défaut
    # sur 100% des incidents. Le coût par incident reste tracé via model_id.
    if rca_result.confidence < settings.ROUTING_ESCALATION_THRESHOLD:
        logger.info(
            "[%s] Confiance insuffisante avec %s (%d%% < %d%%) — escalade vers %s",
            NODE_NAME,
            rca_result.model_id,
            rca_result.confidence,
            settings.ROUTING_ESCALATION_THRESHOLD,
            settings.BEDROCK_SONNET_MODEL_ID,
        )
        rca_result = _bedrock_client.diagnose(
            alarm=alarm,
            logs_text=logs_text,
            model_id=settings.BEDROCK_SONNET_MODEL_ID,
        )
        state.add_trace(
            NODE_NAME,
            f"escalade FinOps vers {settings.BEDROCK_SONNET_MODEL_ID}",
        )

    alarm_context_text = (
        f"{alarm.alarm_name} {alarm.reason or ''} {alarm.metric_name or ''} "
        f"{alarm.threshold if alarm.threshold is not None else ''}"
    )
    rca_result.groundedness_score = compute_groundedness_score(
        rca_result,
        logs_text,
        alarm_context_text=alarm_context_text,
    )

    state.rca = rca_result

    state.add_trace(
        NODE_NAME,
        f"diagnosis='{rca_result.diagnosis}' confidence={rca_result.confidence} "
        f"model={rca_result.model_id} groundedness={rca_result.groundedness_score}",
    )

    # US 2.4 : log best-effort — ne doit jamais interrompre le graphe.
    groundedness_extra = (
        {"groundedness_score": Decimal(str(rca_result.groundedness_score))}
        if rca_result.groundedness_score is not None
        else None
    )

    _decision_logger.log_node_contribution(
        incident_id=state.incident_id,
        node_name=NODE_NAME,
        alarm_type=alarm.alarm_type,
        rca_diagnosis=rca_result.diagnosis,
        confidence=rca_result.confidence,
        tokens_used=rca_result.tokens_used,
        extra={
            **(groundedness_extra or {}),
            "model_id": rca_result.model_id,  # comparaison Haiku vs Sonnet (US 4.5)
        },
    )

    logger.info(
        "[%s] Diagnostic terminé pour incident_id=%s: %s (model=%s, confidence=%d, groundedness=%s)",
        NODE_NAME,
        state.incident_id,
        rca_result.diagnosis,
        rca_result.model_id,
        rca_result.confidence,
        rca_result.groundedness_score,
    )

    return {"state": state}
