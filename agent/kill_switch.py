from __future__ import annotations

import logging

import boto3
from botocore.exceptions import ClientError

from agent.config import settings

logger = logging.getLogger(__name__)

KILL_SWITCH_PARAMETER_NAME = "/agent-devops/kill_switch"
ENABLED_VALUE = "ENABLED"


class KillSwitch:
    def __init__(self, ssm_client=None):
        self._client = ssm_client or boto3.client(
            "ssm", region_name=settings.AWS_REGION
        )

    def is_agent_enabled(self) -> bool:
        try:
            response = self._client.get_parameter(Name=KILL_SWITCH_PARAMETER_NAME)
            value = response["Parameter"]["Value"].strip().upper()
            enabled = value == ENABLED_VALUE
            if not enabled:
                logger.warning(
                    "Kill switch engagé : paramètre %s='%s' — agent désactivé.",
                    KILL_SWITCH_PARAMETER_NAME,
                    value,
                )
            return enabled
        except ClientError:
            logger.exception(
                "Kill switch illisible (fail-closed, agent considéré désactivé)",
            )
            return False
        except Exception:
            logger.exception(
                "Erreur inattendue lors de la lecture du kill switch "
                "(fail-closed, agent considéré désactivé)"
            )
            return False
