from __future__ import annotations

import logging

import requests

from agent.config import settings
from agent.graph.build_graph import graph
from agent.graph_invocation import resume_graph
from agent.pending_validations import list_expired_validations, try_claim_validation

logger = logging.getLogger(__name__)


def handler(event, context):
    expired = list_expired_validations()
    processed = 0

    for item in expired:
        incident_id = item["incident_id"]

        if not try_claim_validation(incident_id):
            logger.info(
                "Incident %s déjà réclamé (probable clic humain concurrent) — "
                "timeout ignoré pour cet item",
                incident_id,
            )
            continue

        result = resume_graph(
            graph,
            incident_id=incident_id,
            approved=False,
            validator="system_timeout",
            reason=f"Timeout de validation ({settings.VALIDATION_TIMEOUT_MINUTES} min) — annulation par défaut",
        )

        final_status = (
            result.get("state").decision.status.value
            if "state" in result
            else "voir logs"
        )
        _notify_timeout(incident_id, final_status)
        processed += 1

    return {"processed": processed, "candidates": len(expired)}


def _notify_timeout(incident_id: str, final_status: str) -> None:
    """Notifie le timeout de validation sur Slack."""
    text = (
        f"*⏱️ Timeout de validation — incident `{incident_id}`*\n"
        f"Aucune réponse humaine sous {settings.VALIDATION_TIMEOUT_MINUTES} min : "
        f"comportement par défaut sûr appliqué.\n"
        f"Statut final : `{final_status}`"
    )
    try:
        response = requests.post(
            settings.SLACK_WEBHOOK_URL, json={"text": text}, timeout=10
        )
        response.raise_for_status()
        logger.info("Notification de timeout envoyée pour %s", incident_id)
    except requests.exceptions.RequestException:
        logger.exception("Échec de l'envoi de la notification Slack")
