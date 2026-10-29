from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent import graph_invocation as gi
from agent.models import DecisionStatus


class TestInvokeGraphWithInterruptHandling:
    def test_no_interrupt_returns_raw_result(self):
        fake_graph = MagicMock()
        fake_graph.invoke.return_value = {"state": "final-state"}

        result = gi.invoke_graph_with_interrupt_handling(
            fake_graph, {"some": "state"}, "inc-1"
        )

        assert result == {"state": "final-state"}
        fake_graph.invoke.assert_called_once()
        args, kwargs = fake_graph.invoke.call_args
        assert args[0] == {"state": {"some": "state"}}
        assert kwargs["config"] == {"configurable": {"thread_id": "inc-1"}}

    @patch.object(gi, "_slack_interactive")
    @patch.object(gi, "register_pending_validation")
    @patch.object(gi, "_decision_dynamo_logger")
    def test_interrupt_registers_validation_and_notifies_slack(
        self, mock_logger, mock_register, mock_slack
    ):
        interrupt_payload = MagicMock()
        interrupt_payload.value = {
            "proposed_action": "RestartService",
            "confidence": 40,
        }
        fake_graph = MagicMock()
        fake_graph.invoke.return_value = {"__interrupt__": [interrupt_payload]}

        result = gi.invoke_graph_with_interrupt_handling(
            fake_graph, {"some": "state"}, "inc-2"
        )

        assert result == {
            "status": "AWAITING_HUMAN_VALIDATION",
            "incident_id": "inc-2",
        }
        mock_logger.log_node_contribution.assert_called_once()
        _, kwargs = mock_logger.log_node_contribution.call_args
        assert kwargs["incident_id"] == "inc-2"
        assert kwargs["node_name"] == "Decision"
        assert (
            kwargs["extra"]["decision_status"]
            == DecisionStatus.AWAITING_HUMAN_VALIDATION.value
        )
        assert kwargs["extra"]["proposed_action"] == "RestartService"
        assert kwargs["extra"]["confidence"] == 40

        mock_register.assert_called_once_with("inc-2")
        mock_slack.send_validation_request.assert_called_once()


class TestResumeGraph:
    @patch("agent.pending_validations.clear_pending_validation")
    def test_resume_graph_invokes_with_command_and_clears_validation(self, mock_clear):
        fake_graph = MagicMock()
        fake_graph.invoke.return_value = {"state": "resumed"}

        result = gi.resume_graph(
            fake_graph,
            incident_id="inc-3",
            approved=True,
            validator="alice",
            reason=None,
        )

        assert result == {"state": "resumed"}
        fake_graph.invoke.assert_called_once()
        args, kwargs = fake_graph.invoke.call_args
        # Command(resume=payload) — vérifie via l'attribut resume
        assert args[0].resume["approved"] is True
        assert args[0].resume["validator"] == "alice"
        assert kwargs["config"] == {"configurable": {"thread_id": "inc-3"}}
        mock_clear.assert_called_once_with("inc-3")

    @patch("agent.pending_validations.clear_pending_validation")
    def test_resume_graph_rejected_with_reason(self, mock_clear):
        fake_graph = MagicMock()
        fake_graph.invoke.return_value = {"state": "resumed"}

        gi.resume_graph(
            fake_graph,
            incident_id="inc-4",
            approved=False,
            validator="system_timeout",
            reason="Timeout",
        )

        args, _ = fake_graph.invoke.call_args
        assert args[0].resume["approved"] is False
        assert args[0].resume["reason"] == "Timeout"
        mock_clear.assert_called_once_with("inc-4")
