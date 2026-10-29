from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from .constants import ESCALATION_STATUSES, SUCCESS_STATUSES


def _parse_timestamp(value: Any) -> datetime | None:
    """Convertit un timestamp Unix ou ISO en datetime UTC."""
    if value is None:
        return None

    if isinstance(value, (int, float, Decimal)):
        try:
            return datetime.fromtimestamp(
                float(value),
                tz=UTC,
            )
        except (ValueError, OSError, OverflowError):
            return None

    if isinstance(value, str):
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)

            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)

            return parsed.astimezone(UTC)

        except ValueError:
            return None

    return None


def _resolution_seconds(
    item: dict[str, Any],
) -> float | None:
    """Calcule la durée du pipeline de l'agent."""
    if item.get("nb_node_writes", 0) < 2:
        return None

    start = _parse_timestamp(
        item.get("alert_received_at")
        or item.get("first_timestamp")
    )

    end = _parse_timestamp(
        item.get("resolved_at")
        or item.get("action_completed_at")
        or item.get("last_timestamp")
    )

    if start is None or end is None:
        return None

    delta = (end - start).total_seconds()

    if delta < 0:
        return None

    return delta


def taux_succes_execution(items: list[dict[str, Any]]) -> float:
    """Ratio d'incidents résolus avec succès (statuts de succès / total)."""
    if not items:
        return 0.0

    succes = sum(1 for item in items if item.get("status") in SUCCESS_STATUSES)

    return succes / len(items)


def taux_escalade_humaine(items: list[dict[str, Any]]) -> float:
    """Ratio d'incidents ayant nécessité une escalade humaine."""
    if not items:
        return 0.0

    escalades = sum(1 for item in items if item.get("status") in ESCALATION_STATUSES)

    return escalades / len(items)


def mttr_par_type(items: list[dict[str, Any]]) -> dict[str, float]:
    """MTTR (temps moyen de résolution) par type d'alarme.

    Ne prend en compte que les incidents dont le statut indique un succès
    (voir SUCCESS_STATUSES) et pour lesquels une durée de résolution est
    calculable.
    """
    durations_by_type: dict[str, list[float]] = {}

    for item in items:
        if item.get("status") not in SUCCESS_STATUSES:
            continue

        duration = _resolution_seconds(item)

        if duration is None:
            continue

        alarm_type = item.get("alarm_type")

        if alarm_type is None:
            continue

        durations_by_type.setdefault(alarm_type, []).append(duration)

    return {
        alarm_type: round(sum(durations) / len(durations), 2)
        for alarm_type, durations in durations_by_type.items()
    }