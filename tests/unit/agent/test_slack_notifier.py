"""
Tests unitaires — agent/slack_notifier.py

Notifier Slack simple (US 3.2). Distinct de
agent/slack_interactive_notifier.py (déjà couvert par test_slack.py),
qui gère les boutons d'action pour la validation humaine — celui-ci ne
fait qu'envoyer un message texte.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from agent.slack_notifier import SlackNotificationError, SlackNotifier


class TestSlackNotifierInit:
    def test_uses_explicit_webhook_and_channel(self):
        notifier = SlackNotifier(
            webhook_url="https://hooks.slack.com/x", channel="#ops"
        )
        assert notifier.webhook_url == "https://hooks.slack.com/x"
        assert notifier.channel == "#ops"

    def test_falls_back_to_settings_when_not_provided(self, monkeypatch):
        monkeypatch.setattr(
            "agent.slack_notifier.settings.SLACK_WEBHOOK_URL",
            "https://hooks.slack.com/default",
        )
        monkeypatch.setattr("agent.slack_notifier.settings.SLACK_CHANNEL", "#default")

        notifier = SlackNotifier()

        assert notifier.webhook_url == "https://hooks.slack.com/default"
        assert notifier.channel == "#default"


class TestSlackNotifierSend:
    def test_missing_webhook_url_raises_before_any_request(self, monkeypatch):
        monkeypatch.setattr("agent.slack_notifier.settings.SLACK_WEBHOOK_URL", None)
        notifier = SlackNotifier(webhook_url=None)

        with pytest.raises(
            SlackNotificationError, match="SLACK_WEBHOOK_URL non configuré"
        ):
            notifier.send("un message")

    @patch("agent.slack_notifier.requests.post")
    def test_successful_send_posts_expected_payload(self, mock_post):
        mock_post.return_value = MagicMock()
        notifier = SlackNotifier(
            webhook_url="https://hooks.slack.com/x", channel="#ops"
        )

        notifier.send("Incident résolu")

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://hooks.slack.com/x"
        assert kwargs["json"] == {"text": "Incident résolu", "channel": "#ops"}
        assert kwargs["timeout"] == 5
        mock_post.return_value.raise_for_status.assert_called_once()

    @patch("agent.slack_notifier.requests.post")
    def test_http_error_raises_slack_notification_error(self, mock_post):
        mock_post.return_value = MagicMock()
        mock_post.return_value.raise_for_status.side_effect = (
            requests.exceptions.HTTPError("500 server error")
        )
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/x")

        with pytest.raises(SlackNotificationError, match="500 server error"):
            notifier.send("un message")

    @patch("agent.slack_notifier.requests.post")
    def test_connection_error_raises_slack_notification_error(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError("dns fail")
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/x")

        with pytest.raises(SlackNotificationError, match="dns fail"):
            notifier.send("un message")

    @patch("agent.slack_notifier.requests.post")
    def test_timeout_error_raises_slack_notification_error(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout("timed out")
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/x")

        with pytest.raises(SlackNotificationError, match="timed out"):
            notifier.send("un message")
