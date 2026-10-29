# tests/test_communication_node.py
from unittest.mock import patch

from agent.graph.nodes.communication_node import communication_node
from agent.models import (
    AlarmPayload,
    AlarmState,
    DecisionResult,
    DecisionStatus,
    GraphState,
    RCAResult,
)
from agent.slack_notifier import SlackNotificationError


def _make_state():
    alarm = AlarmPayload(
        alarm_name="CPUHigh-test",
        alarm_type="CPUHigh",
        new_state=AlarmState.ALARM,
    )
    state = GraphState(incident_id=alarm.incident_id, alarm=alarm)
    state.rca = RCAResult(
        diagnosis="fuite mémoire",
        confidence=90,
        suggested_action="RestartService",
    )
    state.decision = DecisionResult(
        status=DecisionStatus.EXECUTED,
        action="RestartService",
        ssm_command_id="cmd-1",
    )
    return state


@patch("agent.graph.nodes.communication_node._decision_logger")
@patch("agent.graph.nodes.communication_node._slack_notifier")
def test_communication_sends_message_successfully(mock_slack, mock_logger):
    mock_slack.channel = "#devops-alerts"  # <-- ligne à ajouter
    result = communication_node({"state": _make_state()})
    assert result["state"].communication.status.value == "SENT"
    mock_slack.send.assert_called_once()


@patch("agent.graph.nodes.communication_node._decision_logger")
@patch("agent.graph.nodes.communication_node._slack_notifier")
def test_communication_handles_slack_failure_gracefully(mock_slack, mock_logger):
    mock_slack.send.side_effect = SlackNotificationError("webhook injoignable")
    result = communication_node({"state": _make_state()})
    assert result["state"].communication.status.value == "FAILED"
