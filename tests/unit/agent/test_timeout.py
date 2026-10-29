from unittest.mock import MagicMock, patch

import requests

from agent import timeout_checker


def _make_result(status_value: str = "VALIDATION_TIMEOUT_ACTION_CANCELLED"):
    decision = MagicMock()
    decision.status.value = status_value
    state = MagicMock()
    state.decision = decision
    return {"state": state}


class TestHandler:
    @patch("agent.timeout_checker._notify_timeout")
    @patch("agent.timeout_checker.resume_graph")
    @patch("agent.timeout_checker.try_claim_validation")
    @patch("agent.timeout_checker.list_expired_validations")
    def test_no_expired_validations_processes_nothing(
        self, mock_list, mock_claim, mock_resume, mock_notify
    ):
        mock_list.return_value = []

        result = timeout_checker.handler({}, None)

        assert result == {"processed": 0, "candidates": 0}
        mock_claim.assert_not_called()
        mock_resume.assert_not_called()
        mock_notify.assert_not_called()

    @patch("agent.timeout_checker._notify_timeout")
    @patch("agent.timeout_checker.resume_graph")
    @patch("agent.timeout_checker.try_claim_validation")
    @patch("agent.timeout_checker.list_expired_validations")
    def test_expired_validation_is_resumed_as_rejected_and_notified(
        self, mock_list, mock_claim, mock_resume, mock_notify
    ):
        mock_list.return_value = [{"incident_id": "inc-1"}]
        mock_claim.return_value = True
        mock_resume.return_value = _make_result("VALIDATION_TIMEOUT_ACTION_CANCELLED")

        result = timeout_checker.handler({}, None)

        assert result == {"processed": 1, "candidates": 1}
        mock_claim.assert_called_once_with("inc-1")
        _, kwargs = mock_resume.call_args
        assert kwargs["incident_id"] == "inc-1"
        assert kwargs["approved"] is False
        assert kwargs["validator"] == "system_timeout"
        mock_notify.assert_called_once_with(
            "inc-1", "VALIDATION_TIMEOUT_ACTION_CANCELLED"
        )

    @patch("agent.timeout_checker._notify_timeout")
    @patch("agent.timeout_checker.resume_graph")
    @patch("agent.timeout_checker.try_claim_validation")
    @patch("agent.timeout_checker.list_expired_validations")
    def test_validation_already_claimed_is_skipped(
        self, mock_list, mock_claim, mock_resume, mock_notify
    ):
        """Cas de concurrence : un humain a répondu entre le scan et le
        traitement -> le timeout ne doit pas écraser sa décision."""
        mock_list.return_value = [{"incident_id": "inc-2"}]
        mock_claim.return_value = False

        result = timeout_checker.handler({}, None)

        assert result == {"processed": 0, "candidates": 1}
        mock_resume.assert_not_called()
        mock_notify.assert_not_called()

    @patch("agent.timeout_checker._notify_timeout")
    @patch("agent.timeout_checker.resume_graph")
    @patch("agent.timeout_checker.try_claim_validation")
    @patch("agent.timeout_checker.list_expired_validations")
    def test_multiple_expired_validations_all_processed(
        self, mock_list, mock_claim, mock_resume, mock_notify
    ):
        mock_list.return_value = [
            {"incident_id": "inc-1"},
            {"incident_id": "inc-2"},
            {"incident_id": "inc-3"},
        ]
        mock_claim.side_effect = [True, False, True]
        mock_resume.return_value = _make_result()

        result = timeout_checker.handler({}, None)

        assert result == {"processed": 2, "candidates": 3}
        assert mock_resume.call_count == 2
        assert mock_notify.call_count == 2

    @patch("agent.timeout_checker._notify_timeout")
    @patch("agent.timeout_checker.resume_graph")
    @patch("agent.timeout_checker.try_claim_validation")
    @patch("agent.timeout_checker.list_expired_validations")
    def test_missing_state_in_result_falls_back_to_generic_status(
        self, mock_list, mock_claim, mock_resume, mock_notify
    ):
        mock_list.return_value = [{"incident_id": "inc-4"}]
        mock_claim.return_value = True
        mock_resume.return_value = {}  # pas de "state" dans le résultat

        timeout_checker.handler({}, None)

        mock_notify.assert_called_once_with("inc-4", "voir logs")


class TestNotifyTimeout:
    def test_posts_message_with_incident_id_and_status(self, monkeypatch):
        monkeypatch.setattr(
            timeout_checker.settings, "SLACK_WEBHOOK_URL", "https://hooks.example/x"
        )
        monkeypatch.setattr(timeout_checker.settings, "VALIDATION_TIMEOUT_MINUTES", 15)
        mock_response = MagicMock()
        with patch(
            "agent.timeout_checker.requests.post", return_value=mock_response
        ) as mock_post:
            timeout_checker._notify_timeout("inc-99", "REJECTED_BY_HUMAN")

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://hooks.example/x"
        assert "inc-99" in kwargs["json"]["text"]
        assert "REJECTED_BY_HUMAN" in kwargs["json"]["text"]
        assert "15" in kwargs["json"]["text"]
        mock_response.raise_for_status.assert_called_once()

    def test_request_exception_is_swallowed_not_raised(self, monkeypatch):
        """Best-effort : un échec Slack ne doit jamais faire planter le
        handler (le kill switch/timeout par défaut a déjà été appliqué)."""
        monkeypatch.setattr(
            timeout_checker.settings, "SLACK_WEBHOOK_URL", "https://hooks.example/x"
        )
        with patch(
            "agent.timeout_checker.requests.post",
            side_effect=requests.exceptions.ConnectionError("dns fail"),
        ):
            # Ne doit pas lever
            timeout_checker._notify_timeout("inc-1", "ERROR")

    def test_http_error_status_is_swallowed_not_raised(self, monkeypatch):
        monkeypatch.setattr(
            timeout_checker.settings, "SLACK_WEBHOOK_URL", "https://hooks.example/x"
        )
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "500 server error"
        )
        with patch("agent.timeout_checker.requests.post", return_value=mock_response):
            timeout_checker._notify_timeout("inc-1", "ERROR")
