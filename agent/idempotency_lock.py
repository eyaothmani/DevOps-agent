from __future__ import annotations

import dataclasses
import enum
import logging
import time

import boto3
from botocore.exceptions import ClientError

from agent.config import settings

logger = logging.getLogger(__name__)


class LockOutcome(str, enum.Enum):
    ACQUIRED = "ACQUIRED"
    ALREADY_HELD = "ALREADY_HELD"
    ACQUISITION_FAILED = "ACQUISITION_FAILED"


@dataclasses.dataclass
class LockAcquisitionResult:
    outcome: LockOutcome
    detail: str

    @property
    def acquired(self) -> bool:
        return self.outcome is LockOutcome.ACQUIRED


class ActionIdempotencyLock:
    def __init__(
        self,
        table_name: str | None = None,
        dynamodb_resource=None,
    ):
        self._table_name = table_name or settings.ACTION_LOCKS_TABLE
        self._resource = dynamodb_resource or boto3.resource(
            "dynamodb",
            region_name=settings.AWS_REGION,
        )
        self._table = self._resource.Table(self._table_name)

    @staticmethod
    def _lock_key(resource_id: str, action_type: str) -> str:
        return f"{resource_id}#{action_type}"

    def try_acquire_detailed(
        self,
        resource_id: str,
        action_type: str,
        incident_id: str,
        ttl_seconds: int | None = None,
    ) -> LockAcquisitionResult:
        """Acquiert un verrou pour (resource_id, action_type).

        US 4.4 — un verrou existant n'est franchissable que si expires_at
        est dépassé. Cela fournit un vrai cooldown à partir de
        l'acquisition du verrou.

        Distingue un doublon réel d'une panne technique DynamoDB afin
        de ne pas masquer une panne d'infrastructure.
        """
        ttl = (
            ttl_seconds if ttl_seconds is not None else settings.IDEMPOTENCY_TTL_SECONDS
        )
        lock_key = self._lock_key(resource_id, action_type)
        now = int(time.time())

        try:
            self._table.put_item(
                Item={
                    "lock_key": lock_key,
                    "resource_id": resource_id,
                    "action_type": action_type,
                    "incident_id": incident_id,
                    "created_at": now,
                    "expires_at": now + ttl,
                },
                ConditionExpression=(
                    "attribute_not_exists(lock_key) OR expires_at < :now"
                ),
                ExpressionAttributeValues={":now": now},
            )

            logger.info(
                "Verrou d'idempotence acquis (cooldown %ds) : "
                "lock_key=%s incident_id=%s",
                ttl,
                lock_key,
                incident_id,
            )

            return LockAcquisitionResult(
                outcome=LockOutcome.ACQUIRED,
                detail=f"Verrou acquis pour {ttl}s.",
            )

        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")

            if error_code == "ConditionalCheckFailedException":
                logger.warning(
                    "Verrou d'idempotence actif (cooldown en cours) : "
                    "lock_key=%s incident_id=%s",
                    lock_key,
                    incident_id,
                )

                return LockAcquisitionResult(
                    outcome=LockOutcome.ALREADY_HELD,
                    detail=(
                        "Verrou déjà détenu : action déjà en cours "
                        "ou déjà exécutée pour cette instance."
                    ),
                )

            logger.exception(
                "Échec technique DynamoDB lors de l'acquisition du verrou "
                "(fail-closed, action non exécutée par prudence) : "
                "lock_key=%s",
                lock_key,
            )

            return LockAcquisitionResult(
                outcome=LockOutcome.ACQUISITION_FAILED,
                detail=(
                    "Panne technique lors de l'acquisition "
                    f"du verrou d'idempotence : {exc}"
                ),
            )

    def try_acquire(
        self,
        resource_id: str,
        action_type: str,
        incident_id: str,
        ttl_seconds: int | None = None,
    ) -> bool:
        """Conserve la compatibilité avec les anciens appelants."""
        return self.try_acquire_detailed(
            resource_id,
            action_type,
            incident_id,
            ttl_seconds,
        ).acquired

    def release(
        self,
        resource_id: str,
        action_type: str,
    ) -> bool:
        lock_key = self._lock_key(resource_id, action_type)

        try:
            self._table.delete_item(Key={"lock_key": lock_key})

            logger.info(
                "Verrou d'idempotence relâché : lock_key=%s",
                lock_key,
            )
            return True

        except ClientError:
            logger.exception(
                "Échec de la libération du verrou d'idempotence "
                "(best-effort, ignoré) : lock_key=%s",
                lock_key,
            )
            return False
