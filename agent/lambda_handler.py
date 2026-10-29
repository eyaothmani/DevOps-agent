"""
lambda_handler.py

Point d'entrée de la Lambda — invoquée par SNS,
parse l'alarme et lance le graphe.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from agent.alarm_parser import AlarmParsingError, parse_lambda_event
from agent.graph.build_graph import graph
from agent.graph_invocation import invoke_graph_with_interrupt_handling
from agent.models import GraphState

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _build_initial_state(alarm) -> GraphState:
    """Construit l'état initial du graphe à partir de l'alarme parsée."""
    incident_id = str(uuid.uuid4())

    return GraphState(
        incident_id=incident_id,
        alarm=alarm,
        logs=[],
        rca=None,
        decision=None,
        communication=None,
        trace=[],
    )


def handler(
    event: dict[str, Any],
    context: Any,
) -> dict[str, Any]:
    """Handler Lambda — reçoit l'événement SNS et exécute le graphe."""
    logger.info(
        "Lambda invoquée, event brut reçu : %s",
        event,
    )

    try:
        alarms = parse_lambda_event(event)

    except AlarmParsingError:
        logger.exception(
            "Échec du parsing de l'événement SNS",
        )
        raise

    results = []

    for alarm in alarms:
        logger.info(
            "Alarme parsée -> name=%s type=%s instance_id=%s",
            alarm.alarm_name,
            alarm.alarm_type,
            alarm.instance_id,
        )

        initial_state = _build_initial_state(alarm)
        incident_id = initial_state.incident_id

        try:
            result = invoke_graph_with_interrupt_handling(
                graph,
                initial_state,
                incident_id,
            )

            if result.get("status") == "AWAITING_HUMAN_VALIDATION":
                logger.info(
                    "Incident %s en attente de validation humaine (Slack).",
                    incident_id,
                )

                results.append(
                    {
                        "incident_id": incident_id,
                        "decision_status": "AWAITING_HUMAN_VALIDATION",
                    }
                )

                continue

            final_state = result

            decision_status = (
                final_state["state"].decision.status.value
                if final_state["state"].decision
                else "N/A"
            )

            communication_status = (
                final_state["state"].communication.status.value
                if final_state["state"].communication
                else "N/A"
            )

            logger.info(
                "Graphe terminé pour incident_id=%s : decision=%s communication=%s",
                incident_id,
                decision_status,
                communication_status,
            )

            results.append(
                {
                    "incident_id": incident_id,
                    "decision_status": decision_status,
                    "communication_status": communication_status,
                }
            )

        except Exception as exc:
            logger.exception(
                "Échec de l'exécution du graphe pour l'alarme %s",
                alarm.alarm_name,
            )

            results.append(
                {
                    "alarm_name": alarm.alarm_name,
                    "error": str(exc),
                }
            )

    return {
        "statusCode": 200,
        "processed": len(alarms),
        "results": results,
    }
