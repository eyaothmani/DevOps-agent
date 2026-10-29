from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from agent.slack_interactive_notifier import (
    SlackInteractiveNotifier,
    _validate_slack_url,
)


class TestValidateSlackUrl:
    def test_valid_hooks_url_passes(self):
        _validate_slack_url("https://hooks.slack.com/services/x")

    def test_http_scheme_rejected(self):
        with pytest.raises(ValueError):
            _validate_slack_url("http://hooks.slack.com/services/x")

    def test_unauthorized_host_rejected(self):
        with pytest.raises(ValueError):
            _validate_slack_url("https://evil.example.com/webhook")


class TestSendValidationRequest:
    def _payload(self, action="RestartService"):
        return {
            "incident_id": "inc-1",
            "alarm_type": "CPUHigh",
            "alarm_name": "cpu-high-web",
            "diagnosis": "CPU saturé",
            "proposed_action": action,
            "confidence": 40,
            "judge_verdict": "incertain",
            "reason": "Confiance sous le seuil",
            "instance_id": "i-abc",
        }

    @patch("agent.slack_interactive_notifier.requests.post")
    def test_sends_request_with_action_buttons(self, mock_post):
        mock_post.return_value = MagicMock()
        notifier = SlackInteractiveNotifier(webhook_url="https://hooks.slack.com/services/x")

        notifier.send_validation_request(self._payload(), timeout_minutes=15)

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://hooks.slack.com/services/x"
        assert "RestartService" in kwargs["data"]
        mock_post.return_value.raise_for_status.assert_called_once()

    @patch("agent.slack_interactive_notifier.requests.post")
    def test_none_action_uses_closure_confirmation_text(self, mock_post):
        mock_post.return_value = MagicMock()
        notifier = SlackInteractiveNotifier(webhook_url="https://hooks.slack.com/services/x")

        notifier.send_validation_request(
            self._payload(action="NONE"), timeout_minutes=10
        )

        import json as _json

        _args, kwargs = mock_post.call_args
        body = _json.loads(kwargs["data"])
        full_text = _json.dumps(body)
        assert "confirme la cl" in full_text or "clôture" in _json.dumps(
            body, ensure_ascii=False
        )

    def test_invalid_webhook_url_raises_before_posting(self):
        notifier = SlackInteractiveNotifier(webhook_url="https://evil.example.com/x")
        payload = self._payload()

        with pytest.raises(ValueError):
            notifier.send_validation_request(payload, timeout_minutes=15)

    @patch("agent.slack_interactive_notifier.requests.post")
    def test_request_exception_propagates(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError("dns fail")
        notifier = SlackInteractiveNotifier(webhook_url="https://hooks.slack.com/services/x")
        payload = self._payload()

        with pytest.raises(requests.exceptions.ConnectionError):
            notifier.send_validation_request(payload, timeout_minutes=15)

    def test_uses_settings_webhook_url_by_default(self, monkeypatch):
        monkeypatch.setattr(
            "agent.slack_interactive_notifier.settings.SLACK_WEBHOOK_URL",
            "https://hooks.slack.com/services/default",
        )
        notifier = SlackInteractiveNotifier()
        assert notifier._webhook_url == "https://hooks.slack.com/services/default"