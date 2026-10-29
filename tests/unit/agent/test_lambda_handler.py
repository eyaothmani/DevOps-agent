from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import tests as _tests_package
from agent import lambda_handler
from agent.alarm_parser import AlarmParsingError
from agent.models import CommunicationStatus, DecisionStatus

FIXTURE_PATH = Path(_tests_package.__file__).parent / "fixtures" / "sample_cloudwatch_alarm.json"

@pytest.fixture
def sns_event():
    return json.loads(FIXTURE_PATH.read_text())


class TestBuildInitialState:
    def test_build_initial_state_has_fresh_incident_id(self):
        from agent.models import AlarmPayload, AlarmState

        alarm = AlarmPayload(
            alarm_name="test",
            alarm_type="CPUHigh",
            new_state=AlarmState.ALARM,
        )
        state = lambda_handler._build_initial_state(alarm)
        assert state.alarm is alarm
        assert state.incident_id
        assert state.rca is None
        assert state.decision is None
        assert state.communication is None
        assert state.trace == []


class TestHandler:
    @patch("agent.lambda_handler.invoke_graph_with_interrupt_handling")
    def test_handler_completes_successfully(self, mock_invoke, sns_event):
        fake_state = MagicMock()
        fake_state.decision.status.value = DecisionStatus.EXECUTED.value
        fake_state.communication.status.value = CommunicationStatus.SENT.value
        mock_invoke.return_value = {"state": fake_state}

        result = lambda_handler.handler(sns_event, None)

        assert result["statusCode"] == 200
        assert result["processed"] == 1
        assert result["results"][0]["decision_status"] == "EXECUTED"
        assert result["results"][0]["communication_status"] == "SENT"

    @patch("agent.lambda_handler.invoke_graph_with_interrupt_handling")
    def test_handler_handles_missing_decision_and_communication(
        self, mock_invoke, sns_event
    ):
        fake_state = MagicMock()
        fake_state.decision = None
        fake_state.communication = None
        mock_invoke.return_value = {"state": fake_state}

        result = lambda_handler.handler(sns_event, None)

        assert result["results"][0]["decision_status"] == "N/A"
        assert result["results"][0]["communication_status"] == "N/A"

    @patch("agent.lambda_handler.invoke_graph_with_interrupt_handling")
    def test_handler_awaiting_human_validation_is_not_an_error(
        self, mock_invoke, sns_event
    ):
        mock_invoke.return_value = {
            "status": "AWAITING_HUMAN_VALIDATION",
            "incident_id": "inc-xyz",
        }

        result = lambda_handler.handler(sns_event, None)

        assert result["processed"] == 1
        assert result["results"][0]["decision_status"] == "AWAITING_HUMAN_VALIDATION"
        assert "incident_id" in result["results"][0]

    @patch("agent.lambda_handler.invoke_graph_with_interrupt_handling")
    def test_handler_catches_graph_exception_and_continues(
        self, mock_invoke, sns_event
    ):
        mock_invoke.side_effect = RuntimeError("boom")

        result = lambda_handler.handler(sns_event, None)

        assert result["processed"] == 1
        assert "error" in result["results"][0]
        assert result["results"][0]["error"] == "boom"

    def test_handler_reraises_alarm_parsing_error(self):
        with (
            patch(
                "agent.lambda_handler.parse_lambda_event",
                side_effect=AlarmParsingError("bad event"),
            ),
            pytest.raises(AlarmParsingError),
        ):
            lambda_handler.handler({"Records": []}, None)

    @patch("agent.lambda_handler.invoke_graph_with_interrupt_handling")
    def test_handler_processes_multiple_alarms_independently(
        self, mock_invoke, sns_event
    ):
        # Duplique le record pour simuler 2 alarmes dans le même event SNS.
        multi_event = {"Records": sns_event["Records"] * 2}

        fake_state_1 = MagicMock()
        fake_state_1.decision.status.value = "EXECUTED"
        fake_state_1.communication.status.value = "SENT"

        mock_invoke.side_effect = [
            {"state": fake_state_1},
            RuntimeError("second alarm failed"),
        ]

        result = lambda_handler.handler(multi_event, None)

        assert result["processed"] == 2
        assert len(result["results"]) == 2
        assert result["results"][0]["decision_status"] == "EXECUTED"
        assert result["results"][1]["error"] == "second alarm failed"