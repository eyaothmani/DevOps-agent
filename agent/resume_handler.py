from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.parse
from urllib.parse import urlparse

import boto3
import requests

from agent.config import settings
from agent.graph_invocation import resume_graph

logger = logging.getLogger(__name__)

_lambda_client = None


def _get_lambda_client():
    """Crée le client boto3 lambda à la demande (lazy init).

    Évite d'appeler boto3.client() au moment de l'import du module,
    ce qui plantait en environnement sans région AWS configurée
    (ex: CI, tests unitaires) avec l'erreur :
    ValueError: Invalid endpoint: https://lambda..amazonaws.com
    """
    global _lambda_client
    if _lambda_client is None:
        _lambda_client = boto3.client("lambda")
    return _lambda_client


# ---------- Validation des URLs ----------
def _validate_slack_url(url: str) -> None:
    """Lève une exception si l'URL n'est pas une URL Slack valide (HTTPS)."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"URL Slack non sécurisée (schéma invalide : {parsed.scheme})")
    allowed_hosts = ("hooks.slack.com", "slack.com", "slack-edge.com")
    if not any(parsed.netloc.endswith(host) for host in allowed_hosts):
        raise ValueError(f"URL Slack non autorisée (hôte : {parsed.netloc})")


# ---------- Signature Slack ----------
def _verify_slack_signature(headers: dict, raw_body: str) -> bool:
    headers_lower = {k.lower(): v for k, v in headers.items()}
    timestamp = headers_lower.get("x-slack-request-timestamp", "0")
    slack_signature = headers_lower.get("x-slack-signature", "")
    try:
        if abs(time.time() - int(timestamp)) > 60 * 5:
            logger.warning(
                "Signature Slack rejetée : timestamp hors fenêtre (timestamp=%s)",
                timestamp,
            )
            return False
    except ValueError:
        logger.warning(
            "Signature Slack rejetée : timestamp invalide reçu=%r", timestamp
        )
        return False

    basestring = f"v0:{timestamp}:{raw_body}"
    computed = (
        "v0="
        + hmac.new(
            settings.SLACK_SIGNING_SECRET.encode(),
            basestring.encode(),
            hashlib.sha256,
        ).hexdigest()
    )
    match = hmac.compare_digest(computed, slack_signature)
    if not match:
        logger.warning("Signature Slack invalide : mismatch HMAC (requête rejetée).")
    return match


# ---------- Handler principal ----------
def handler(event, context):
    logger.debug(
        "resume_handler invoqué — has_headers=%s, _async_resume=%s",
        "headers" in event,
        event.get("_async_resume"),
    )

    if "headers" in event and "body" in event and not event.get("_async_resume"):
        headers = event.get("headers", {})
        raw_body = event.get("body", "")
        if event.get("isBase64Encoded"):
            raw_body = base64.b64decode(raw_body).decode("utf-8")

        if not _verify_slack_signature(headers, raw_body):
            return {"statusCode": 401, "body": "invalid signature"}

        parsed = urllib.parse.parse_qs(raw_body)
        payload = json.loads(parsed["payload"][0])

        action = payload["actions"][0]
        action_id = action["action_id"]
        incident_id = action["value"]
        validator = payload["user"]["username"]
        response_url = payload["response_url"]

        # Validation de l'URL avant tout appel
        try:
            _validate_slack_url(response_url)
        except ValueError:
            logger.exception("URL Slack invalide")
            return {"statusCode": 400, "body": "Invalid Slack URL"}

        approved = action_id == "approve_action"

        from agent.pending_validations import try_claim_validation

        if not try_claim_validation(incident_id):
            logger.info(
                "Incident %s déjà traité ou en cours de traitement — clic ignoré",
                incident_id,
            )
            _post_ack_message(
                response_url,
                incident_id,
                validator,
                approved,
                already_processed=True,
            )
            return {"statusCode": 200, "body": ""}

        _post_ack_message(response_url, incident_id, validator, approved)

        _get_lambda_client().invoke(
            FunctionName=context.invoked_function_arn,
            InvocationType="Event",
            Payload=json.dumps(
                {
                    "_async_resume": True,
                    "incident_id": incident_id,
                    "approved": approved,
                    "validator": validator,
                    "response_url": response_url,
                }
            ),
        )

        return {"statusCode": 200, "body": ""}

    incident_id = event["incident_id"]
    approved = event["approved"]
    validator = event["validator"]
    response_url = event["response_url"]

    # Validation de l'URL avant appel asynchrone
    try:
        _validate_slack_url(response_url)
    except ValueError:
        logger.exception("URL Slack invalide dans l'appel asynchrone")
        return {"statusCode": 400, "body": "Invalid Slack URL"}

    try:
        # Import différé volontairement : construire le graphe LangGraph
        # (Bedrock, checkpointer DynamoDB, tous les nodes) est coûteux au
        # cold start Lambda. Ce chemin async est le seul endroit du fichier
        # qui en a besoin — le chemin synchrone (accusé de réception à
        # Slack, contrainte de 3 secondes) ne doit jamais payer ce coût.
        from agent.graph.build_graph import graph

        result = resume_graph(
            graph,
            incident_id=incident_id,
            approved=approved,
            validator=validator,
            reason=None if approved else "Rejeté via Slack",
        )
        final_status = (
            result.get("state").decision.status.value
            if "state" in result
            else "voir logs"
        )
    except Exception:
        logger.exception(
            "Échec du traitement asynchrone de la reprise pour incident_id=%s",
            incident_id,
        )
        final_status = "ERROR"

    _update_slack_message(response_url, incident_id, validator, final_status)
    return {"statusCode": 200, "body": ""}


# ---------- Status labels ----------
_STATUS_LABELS = {
    "EXECUTED": "✅ Approuvé et exécuté avec succès",
    "NO_ACTION_CONFIRMED_BY_HUMAN": "✅ Clôture confirmée — aucune action requise",
    "REJECTED_BY_HUMAN": "❌ Rejeté par l'humain",
    "VALIDATION_STALE_ACTION_SKIPPED": "⚠️ Approuvé mais ignoré — situation déjà résolue entre-temps",
    "VALIDATION_STALE_RECONFIRMATION_REQUIRED": "🔁 Situation dégradée depuis le diagnostic — re-triage requis",
    "VALIDATION_TIMEOUT_ACTION_CANCELLED": "⏱️ Délai de validation dépassé — action annulée par défaut",
    "REFUSED_BY_WHITELIST": "🛡️ Action refusée par la whitelist",
    "DUPLICATE_ACTION_SKIPPED": "🔒 Action ignorée — verrou d'idempotence déjà actif",
    "EXECUTION_FAILED": "🔴 Échec de l'exécution SSM",
    "EXECUTION_TIMED_OUT": "🔴 Délai d'exécution SSM dépassé",
    "REMEDIATION_UNAVAILABLE": "🔴 Remédiation indisponible sur l'instance cible",
    "ERROR": "🔴 Erreur pendant le traitement — voir logs CloudWatch",
}


def _status_label(final_status: str) -> str:
    return _STATUS_LABELS.get(
        final_status, f"ℹ️ Statut : {final_status.replace('_', ' ').title()}"
    )


# ---------- Fonctions de post (sécurisées) ----------
def _post_ack_message(
    response_url: str,
    incident_id: str,
    validator: str,
    approved: bool,
    already_processed: bool = False,
) -> None:
    if already_processed:
        text = (
            f"*Incident `{incident_id}`* — déjà traité (clic ignoré, "
            "une seule réponse est prise en compte par incident)."
        )
    else:
        verb = "Approuvé" if approved else "Rejeté"
        text = (
            f"*Incident `{incident_id}`* — {verb} par {validator}, traitement en cours…"
        )

    body = json.dumps({"replace_original": "true", "text": text})
    headers = {"Content-Type": "application/json"}

    # Utilisation de requests.post avec validation déjà faite
    try:
        resp = requests.post(response_url, data=body, headers=headers, timeout=10)
        resp.raise_for_status()
    except requests.RequestException:
        logger.exception("Échec de l'envoi du message Slack (post_ack)")
        raise


def _update_slack_message(
    response_url: str,
    incident_id: str,
    validator: str,
    final_status: str,
) -> None:
    label = _status_label(final_status)
    text = f"*Incident `{incident_id}` — {label}*\nValidé par : {validator}"
    body = json.dumps({"replace_original": "true", "text": text})
    headers = {"Content-Type": "application/json"}

    try:
        resp = requests.post(response_url, data=body, headers=headers, timeout=10)
        resp.raise_for_status()
    except requests.RequestException:
        logger.exception("Échec de l'envoi du message Slack (update)")
        raise