from __future__ import annotations

import logging

from agent.dynamo_logger import DynamoDecisionLogger
from agent.graph.state import AgentState
from agent.models import CommunicationResult, CommunicationStatus
from agent.slack_notifier import SlackNotificationError, SlackNotifier

logger = logging.getLogger(__name__)
NODE_NAME = "Communication"

_decision_logger = DynamoDecisionLogger()
_slack_notifier = SlackNotifier()


def _build_message(state) -> str:
    rca = state.rca
    decision = state.decision
    lines = [
        f"*Incident* `{state.incident_id}` — {state.alarm.alarm_name} ({state.alarm.alarm_type})",
        (
            f"*Diagnostic* (confiance {rca.confidence}%) : {rca.diagnosis}"
            if rca
            else "*Diagnostic* : indisponible"
        ),
        f"*Action* : {decision.status.value}"
        + (f" — {decision.action}" if decision and decision.action else ""),
    ]
    if decision and decision.detail:
        lines.append(f"*Motif* : {decision.detail}")
    return "\n".join(lines)


def communication_node(agent_state: AgentState) -> dict:
    state = agent_state["state"]
    message = _build_message(state)

    try:
        _slack_notifier.send(message)
        state.communication = CommunicationResult(
            status=CommunicationStatus.SENT,
            message_preview=message[:200],
            channel=_slack_notifier.channel,
        )
    except SlackNotificationError:
        logger.exception(
            "[%s] Échec d'envoi Slack pour %s",
            NODE_NAME,
            state.incident_id,
        )
        state.communication = CommunicationResult(
            status=CommunicationStatus.FAILED, message_preview=message[:200]
        )

    state.add_trace(NODE_NAME, f"statut={state.communication.status.value}")
    _decision_logger.log_node_contribution(
        incident_id=state.incident_id,
        node_name=NODE_NAME,
        alarm_type=state.alarm.alarm_type,
        extra={"communication_status": state.communication.status.value},
    )
    return {"state": state}
