from __future__ import annotations

import dataclasses
import logging
import time
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

from agent.config import settings

logger = logging.getLogger(__name__)

# Fenêtre courte et bornée des deux côtés, ancrée sur l'heure de l'ALARME
# (et non sur l'heure d'exécution du node) — évite qu'un run de chaos
# antérieur, le même jour, pollue le diagnostic en cours.
_WINDOW_BEFORE_SECONDS = getattr(settings, "LOG_WINDOW_BEFORE_SECONDS", 10 * 60)
_WINDOW_AFTER_SECONDS = getattr(settings, "LOG_WINDOW_AFTER_SECONDS", 60)
_MAX_EVENTS_PER_GROUP = getattr(settings, "LOG_MAX_EVENTS_PER_GROUP", 50)


@dataclasses.dataclass
class LogEntry:
    source: str
    log_group: str
    timestamp: int
    message: str


def _infer_source(log_stream_name: str) -> str:
    if "syslog" in log_stream_name:
        return "infra"
    if "apache" in log_stream_name:
        return "app"
    return "unknown"


def _parse_anchor_epoch_ms(around_time: str | datetime | None) -> int:
    """Convertit l'heure de référence (timestamp de l'alarme) en epoch ms.
    Si absente (appel legacy ou test), retombe sur l'heure actuelle — mais
    ce cas ne doit plus se produire depuis diagnostic_node."""
    if around_time is None:
        logger.warning(
            "fetch_recent_logs appelé sans around_time — repli sur l'heure "
            "actuelle, risque de fenêtre non ancrée sur l'alarme."
        )
        return int(time.time() * 1000)
    dt = datetime.fromisoformat(around_time) if isinstance(around_time, str) else around_time
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def _fetch_from_group(
    client, log_group: str, instance_id: str | None, anchor_epoch_ms: int
) -> list[LogEntry]:
    """Interroge le groupe de logs CloudWatch partagé et récupère tous les
    streams correspondant au préfixe instance_id (convention CloudWatch Agent :
    {instance_id}/{stream_type}, ex: i-xxx/syslog, i-xxx/apache-access).

    La fenêtre est bornée des DEUX côtés autour de l'heure de l'alarme
    (anchor_epoch_ms), pas glissante depuis l'instant d'exécution du code."""
    entries: list[LogEntry] = []
    try:
        start_time_ms = anchor_epoch_ms - _WINDOW_BEFORE_SECONDS * 1000
        end_time_ms = anchor_epoch_ms + _WINDOW_AFTER_SECONDS * 1000
        kwargs = {
            "logGroupName": log_group,
            "startTime": start_time_ms,
            "endTime": end_time_ms,
            "interleaved": True,
            "limit": _MAX_EVENTS_PER_GROUP,
        }
        if instance_id:
            kwargs["logStreamNamePrefix"] = f"{instance_id}/"

        response = client.filter_log_events(**kwargs)
        for event in response.get("events", []):
            stream_name = event.get("logStreamName", "")
            entries.append(
                LogEntry(
                    source=_infer_source(stream_name),
                    log_group=log_group,
                    timestamp=event.get("timestamp", 0),
                    message=event.get("message", ""),
                )
            )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "ResourceNotFoundException":
            logger.warning("Groupe de logs '%s' introuvable.", log_group)
        else:
            logger.warning(
                "Échec de récupération des logs depuis '%s' : %s",
                log_group,
                exc,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Erreur inattendue lors de la lecture de '%s' : %s", log_group, exc
        )

    return entries


def fetch_recent_logs(
    instance_id: str | None, around_time: str | datetime | None = None
) -> list[LogEntry]:
    """Récupère les logs autour de l'heure de l'alarme (app + infra) depuis
    le groupe partagé. Best-effort : jamais d'exception, liste vide si rien
    trouvé.

    around_time : timestamp de l'alarme (alarm.timestamp), PAS l'heure
    d'exécution du node. C'est ce qui empêche un run de chaos antérieur
    le même jour de polluer le diagnostic de l'incident courant.
    """
    anchor_epoch_ms = _parse_anchor_epoch_ms(around_time)
    client = boto3.client("logs", region_name=settings.AWS_REGION)
    entries = _fetch_from_group(
        client, settings.LOG_GROUP, instance_id, anchor_epoch_ms
    )
    entries.sort(key=lambda e: e.timestamp)
    return entries


def format_logs_for_prompt(logs: list[LogEntry]) -> str:
    if not logs:
        return "Aucun log disponible pour cette instance sur la fenêtre observée."

    lines = [f"[{log.source}] {log.message.strip()}" for log in logs]
    return "\n".join(lines)
