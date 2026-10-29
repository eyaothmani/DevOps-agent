from __future__ import annotations

import logging
from datetime import UTC, datetime

from langgraph.types import Command

from agent.config import settings
from agent.dynamo_logger import DynamoDecisionLogger
from agent.models import DecisionStatus
from agent.pending_validations import register_pending_validation
from agent.slack_interactive_notifier import SlackInteractiveNotifier

logger = logging.getLogger(__name__)

_decision_dynamo_logger = DynamoDecisionLogger()
_slack_interactive = SlackInteractiveNotifier()


def invoke_graph_with_interrupt_handling(
    graph, incident_state: dict, incident_id: str
) -> dict:
    config = {"configurable": {"thread_id": incident_id}}
    result = graph.invoke({"state": incident_state}, config=config)

    if "__interrupt__" in result:
        interrupt_payload = result["__interrupt__"][0].value

        _decision_dynamo_logger.log_node_contribution(
            incident_id=incident_id,
            node_name="Decision",
            extra={
                "decision_status": DecisionStatus.AWAITING_HUMAN_VALIDATION.value,
                "proposed_action": interrupt_payload.get("proposed_action"),
                "confidence": interrupt_payload.get("confidence"),
            },
        )

        register_pending_validation(incident_id)
        _slack_interactive.send_validation_request(
            interrupt_payload,
            timeout_minutes=settings.VALIDATION_TIMEOUT_MINUTES,
        )

        logger.info("Incident %s en attente de validation humaine", incident_id)
        return {
            "status": "AWAITING_HUMAN_VALIDATION",
            "incident_id": incident_id,
        }

    return result


def resume_graph(
    graph,
    incident_id: str,
    approved: bool,
    validator: str,
    reason: str | None = None,
) -> dict:
    from agent.pending_validations import clear_pending_validation

    config = {"configurable": {"thread_id": incident_id}}
    resume_payload = {
        "approved": approved,
        "validator": validator,
        "reason": reason,
        "validated_at": datetime.now(UTC).isoformat(),
    }

    result = graph.invoke(Command(resume=resume_payload), config=config)
    clear_pending_validation(incident_id)
    return result
