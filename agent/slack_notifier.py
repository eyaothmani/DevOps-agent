"""US 3.2 — Envoi de notifications via Slack Incoming Webhook."""

from __future__ import annotations

import logging

import requests

from agent.config import settings

logger = logging.getLogger(__name__)


class SlackNotificationError(Exception):
    """Levée quand l'envoi du message Slack échoue."""


class SlackNotifier:
    def __init__(self, webhook_url: str | None = None, channel: str | None = None):
        self.webhook_url = webhook_url or settings.SLACK_WEBHOOK_URL
        self.channel = channel or settings.SLACK_CHANNEL

    def send(self, message: str) -> None:
        if not self.webhook_url:
            raise SlackNotificationError("SLACK_WEBHOOK_URL non configuré.")
        try:
            response = requests.post(
                self.webhook_url,
                json={"text": message, "channel": self.channel},
                timeout=5,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SlackNotificationError(str(exc)) from exc
