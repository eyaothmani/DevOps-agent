from __future__ import annotations

import logging
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

from agent.config import settings

logger = logging.getLogger(__name__)


class DynamoDecisionLogger:
    def __init__(
        self,
        table_name: str | None = None,
        dynamodb_resource=None,
    ):
        self._table_name = table_name or settings.AGENT_DECISIONS_TABLE
        self._injected_resource = dynamodb_resource

    @property
    def _table(self):
        resource = self._injected_resource or boto3.resource(
            "dynamodb",
            region_name=settings.AWS_REGION,
        )
        return resource.Table(self._table_name)

    def log_node_contribution(
        self,
        incident_id: str,
        node_name: str,
        alarm_type: str | None = None,
        rca_diagnosis: str | None = None,
        confidence: int | None = None,
        tokens_used: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> bool:
        now = int(time.time())

        item: dict[str, Any] = {
            "incident_id": incident_id,
            "node_timestamp": f"{node_name}#{time.time_ns()}",
            "node_name": node_name,
            "timestamp": now,
            "expires_at": (now + settings.AGENT_DECISIONS_RETENTION_DAYS * 86400),
        }

        if alarm_type is not None:
            item["alarm_type"] = alarm_type

        if rca_diagnosis is not None:
            item["rca_diagnosis"] = rca_diagnosis

        if confidence is not None:
            item["confidence"] = confidence

        if tokens_used is not None:
            item["tokens_used"] = tokens_used

        if extra:
            item.update(extra)

        try:
            self._table.put_item(Item=item)
            return True

        except ClientError:
            logger.exception(
                "Échec d'écriture DynamoDB (non bloquant) pour incident_id=%s, node=%s",
                incident_id,
                node_name,
            )
            return False

        except Exception:
            logger.exception("Erreur inattendue lors du log DynamoDB (non bloquant)")
        return False
