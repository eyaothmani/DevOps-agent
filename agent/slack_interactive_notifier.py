from __future__ import annotations

import json
import logging
import time
from urllib.parse import urlparse

import requests

from agent.config import settings

logger = logging.getLogger(__name__)

# Marges de sécurité sous les limites Slack Block Kit :
# - un section.text.text (mrkdwn) est plafonné à 3000 caractères par Slack.
# - on tronque chaque champ variable individuellement, puis on applique
#   un garde-fou global au cas où la somme dépasserait quand même la limite.
_MAX_SECTION_TEXT = 2900
_MAX_DIAGNOSIS_LEN = 1000
_MAX_REASON_LEN = 400


def _truncate(text, max_len: int) -> str:
    if not text:
        return "n/a"
    text = str(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


# ---------- Validation des URLs ----------
def _validate_slack_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"URL Slack non sécurisée (schéma invalide : {parsed.scheme})")
    allowed_hosts = ("hooks.slack.com", "slack.com", "slack-edge.com")
    if not any(parsed.netloc.endswith(host) for host in allowed_hosts):
        raise ValueError(f"URL Slack non autorisée (hôte : {parsed.netloc})")
    if not parsed.path.startswith("/services/"):
        raise ValueError(
            "URL Slack incorrecte : ceci ressemble à une URL d'interactivity "
            "(API Gateway), pas à un Incoming Webhook (attendu : /services/...). "
            f"Path reçu : {parsed.path}"
        )


class SlackInteractiveNotifier:
    def __init__(self, webhook_url: str | None = None):
        self._webhook_url = webhook_url or settings.SLACK_WEBHOOK_URL

    def send_validation_request(self, payload: dict, timeout_minutes: int) -> None:
        incident_id = payload["incident_id"]
        expires_at_ts = int(time.time()) + timeout_minutes * 60
        proposed_action = payload.get("proposed_action")
        is_none_action = proposed_action == "NONE"

        expiry_text = f"<!date^{expires_at_ts}^Expire à {{time}} le {{date_short}}|dans {timeout_minutes} min>"

        if is_none_action:
            consequence_text = (
                "*Ce que signifie chaque choix :*\n"
                "✅ *Approuver* → confirme la clôture : aucune action n'est exécutée, "
                "l'incident est classé résolu avec validation humaine.\n"
                "❌ *Rejeter* → aucune action n'est exécutée non plus, mais l'incident "
                "reste ouvert pour un nouveau triage.\n"
                "⏱️ *Sans réponse avant expiration* → comportement par défaut sûr : "
                "équivalent à un rejet, aucune action exécutée."
            )
        else:
            consequence_text = (
                "*Ce que signifie chaque choix :*\n"
                f"✅ *Approuver* → exécute l'action proposée (`{proposed_action}`) "
                "après revérification de fraîcheur.\n"
                "❌ *Rejeter* → aucune action n'est exécutée.\n"
                "⏱️ *Sans réponse avant expiration* → comportement par défaut sûr : "
                "aucune action exécutée (équivalent à un rejet)."
            )

        # Champs variables tronqués individuellement AVANT assemblage
        diagnosis_text = _truncate(payload.get("diagnosis"), _MAX_DIAGNOSIS_LEN)
        reason_text = _truncate(payload.get("reason"), _MAX_REASON_LEN)

        section_text = (
            f"*🔔 Validation requise — incident `{incident_id}`*\n"
            f"*Alarme :* {payload.get('alarm_type')} ({payload.get('alarm_name')})\n"
            f"*Diagnostic :* {diagnosis_text}\n"
            f"*Action proposée :* `{proposed_action}`\n"
            f"*Confiance :* {payload.get('confidence')}%\n"
            f"*Verdict du juge :* {payload.get('judge_verdict', 'n/a')}\n"
            f"*Motif de l'escalade :* {reason_text}\n"
            f"⏱️ {expiry_text} — passé ce délai, comportement par défaut sûr appliqué automatiquement."
        )

        # Garde-fou global final : défense en profondeur si la somme dépasse
        # quand même la limite malgré les troncatures individuelles.
        if len(section_text) > _MAX_SECTION_TEXT:
            section_text = section_text[: _MAX_SECTION_TEXT - 1].rstrip() + "…"

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": section_text,
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": consequence_text},
            },
            {
                "type": "actions",
                "block_id": f"validation_{incident_id}",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approuver"},
                        "style": "primary",
                        "action_id": "approve_action",
                        "value": incident_id,
                        "confirm": {
                            "title": {
                                "type": "plain_text",
                                "text": "Confirmer",
                            },
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    f"Confirmer la clôture sans action pour `{incident_id}` ?"
                                    if is_none_action
                                    else (
                                        f"Approuver `{proposed_action}` sur "
                                        f"`{payload.get('instance_id')}` ?\nUne revérification "
                                        "de fraîcheur sera effectuée avant exécution."
                                    )
                                ),
                            },
                            "confirm": {
                                "type": "plain_text",
                                "text": "Oui, approuver",
                            },
                            "deny": {"type": "plain_text", "text": "Annuler"},
                        },
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Rejeter"},
                        "style": "danger",
                        "action_id": "reject_action",
                        "value": incident_id,
                    },
                ],
            },
        ]

        # Validation de l'URL avant envoi
        try:
            _validate_slack_url(self._webhook_url)
        except ValueError:
            logger.exception("Webhook URL invalide")
            raise

        body = json.dumps({"blocks": blocks})
        headers = {"Content-Type": "application/json"}

        try:
            resp = requests.post(
                self._webhook_url, data=body, headers=headers, timeout=10
            )
            resp.raise_for_status()
        except requests.RequestException:
            logger.exception(
                "Échec de l'envoi de la demande de validation Slack — réponse : %s",
                getattr(resp, "text", "<pas de réponse>") if "resp" in locals() else "<aucune réponse reçue>",
            )
            raise

        logger.info("Demande de validation envoyée pour incident_id=%s", incident_id)