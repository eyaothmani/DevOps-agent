from __future__ import annotations

import time

import boto3
from botocore.exceptions import ClientError

from agent.config import settings

_table = boto3.resource("dynamodb", region_name=settings.AWS_REGION).Table(
    settings.PENDING_VALIDATIONS_TABLE
)


def register_pending_validation(incident_id: str) -> None:
    now = int(time.time())
    expires_at = now + settings.VALIDATION_TIMEOUT_MINUTES * 60
    _table.put_item(
        Item={
            "incident_id": incident_id,
            "created_at": now,
            "expires_at": expires_at,
            "ttl": expires_at + 3600,  # purge DynamoDB 1h après expiration
        }
    )


def clear_pending_validation(incident_id: str) -> None:
    _table.delete_item(Key={"incident_id": incident_id})


def try_claim_validation(incident_id: str) -> bool:
    """Réclamation atomique d'une validation en attente.

    Empêche qu'un double-clic Slack (ou une retransmission réseau de
    Slack, qui peut renvoyer la même interaction plusieurs fois) ne
    déclenche deux traitements concurrents du même incident : la
    suppression conditionnelle garantit qu'un seul appelant peut
    "gagner" la réclamation — le second échoue proprement au lieu de
    relancer resume_graph() une deuxième fois sur le même graphe.

    Retourne True si CET appel a bien réclamé la validation (premier
    arrivé), False si elle a déjà été réclamée ou traitée (par un
    clic précédent, ou par timeout_checker en cas d'expiration).
    """
    try:
        _table.delete_item(
            Key={"incident_id": incident_id},
            ConditionExpression="attribute_exists(incident_id)",
        )
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def list_expired_validations() -> list[dict]:
    now = int(time.time())
    response = _table.scan(
        FilterExpression="expires_at < :now",
        ExpressionAttributeValues={":now": now},
    )
    return response.get("Items", [])
