from __future__ import annotations

import dataclasses
import enum
import logging

import boto3
from botocore.exceptions import ClientError

from agent.config import settings

logger = logging.getLogger(__name__)

_cloudwatch = boto3.client("cloudwatch", region_name=settings.AWS_REGION)


class FreshnessVerdict(str, enum.Enum):
    STILL_RELEVANT = "STILL_RELEVANT"
    ALARM_RESOLVED = "ALARM_RESOLVED"
    ALARM_WORSENED = "ALARM_WORSENED"
    UNKNOWN = "UNKNOWN"


@dataclasses.dataclass
class FreshnessCheckResult:
    verdict: FreshnessVerdict
    current_alarm_state: str | None
    detail: str


def check_still_relevant(alarm, proposed_action: str) -> FreshnessCheckResult:
    try:
        response = _cloudwatch.describe_alarms(AlarmNames=[alarm.alarm_name])
    except ClientError as exc:
        logger.warning(
            "Revérification CloudWatch impossible pour l'alarme '%s' "
            "(fail-open : action non bloquée par cette erreur technique) : %s",
            alarm.alarm_name,
            exc,
        )
        return FreshnessCheckResult(
            verdict=FreshnessVerdict.UNKNOWN,
            current_alarm_state=None,
            detail=f"Vérification CloudWatch indisponible : {exc}",
        )

    metric_alarms = response.get("MetricAlarms", [])
    if not metric_alarms:
        return FreshnessCheckResult(
            verdict=FreshnessVerdict.UNKNOWN,
            current_alarm_state=None,
            detail=f"Alarme '{alarm.alarm_name}' introuvable lors de la revérification.",
        )

    current_state = metric_alarms[0]["StateValue"]

    if proposed_action != "NONE" and current_state == "OK":
        return FreshnessCheckResult(
            verdict=FreshnessVerdict.ALARM_RESOLVED,
            current_alarm_state=current_state,
            detail=(
                f"L'alarme '{alarm.alarm_name}' est repassée à OK pendant "
                "l'attente de validation : l'action approuvée n'est plus "
                "nécessaire, elle ne sera pas exécutée."
            ),
        )

    if proposed_action == "NONE" and current_state == "ALARM":
        return FreshnessCheckResult(
            verdict=FreshnessVerdict.ALARM_WORSENED,
            current_alarm_state=current_state,
            detail=(
                f"L'alarme '{alarm.alarm_name}' est toujours (ou de nouveau) "
                "active : le diagnostic 'aucune action nécessaire' ne peut "
                "pas être clôturé tel quel, un re-triage est requis."
            ),
        )

    return FreshnessCheckResult(
        verdict=FreshnessVerdict.STILL_RELEVANT,
        current_alarm_state=current_state,
        detail="Situation inchangée depuis le diagnostic initial.",
    )
