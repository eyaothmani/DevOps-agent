"""Reliability, status and failure metrics."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .constants import (
    FAILURE_STATUSES,
    GUARDRAIL_TRIGGER_STATUSES,
    STATUS_DUPLICATE_ACTION_SKIPPED,
    STATUS_REFUSED_BY_WHITELIST,
    STATUS_REMEDIATION_UNAVAILABLE,
)


def status_repartition(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return status distribution."""
    counts: dict[
        str,
        int,
    ] = defaultdict(int)

    for item in items:
        status = item.get(
            "status",
            "UNKNOWN",
        )

        counts[str(status)] += 1

    return [
        {
            "status": status,
            "count": count,
        }
        for status, count in sorted(
            counts.items(),
            key=lambda pair: -pair[1],
        )
    ]


def explain_case(
    item: dict[str, Any],
) -> str:
    """Explain a documented failure."""
    status = item.get(
        "status"
    )

    if (
        status
        == STATUS_DUPLICATE_ACTION_SKIPPED
    ):
        return (
            "Action déjà en cours/récente "
            "sur cette ressource : doublon "
            "bloqué par le verrou "
            "d'idempotence."
        )

    if (
        status
        == STATUS_REFUSED_BY_WHITELIST
    ):
        return (
            "Action proposée par Bedrock "
            "hors whitelist : action refusée."
        )

    if (
        status
        == STATUS_REMEDIATION_UNAVAILABLE
    ):
        return (
            "Remédiation non exécutable : "
            "instance cible non gérée par SSM."
        )

    if (
        item.get("judge_verdict")
        == "incoherent"
    ):
        return (
            "Désaccord entre le score de "
            "confiance et le verdict du juge."
        )

    return (
        "Cas signalé sans catégorie connue "
        "— à vérifier manuellement."
    )

def cas_echec_documentes(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build documented failure cases."""
    cases: list[
        dict[str, Any]
    ] = []

    for item in items:
        status = item.get(
            "status"
        )

        is_guardrail = (
            status
            in GUARDRAIL_TRIGGER_STATUSES
        )

        is_failure = (
            status
            in FAILURE_STATUSES
        )

        judge_incoherent = (
            item.get(
                "judge_verdict"
            )
            == "incoherent"
        )

        if not (
            is_guardrail
            or is_failure
            or judge_incoherent
        ):
            continue

        cases.append(
            {
                "incident_id": item.get(
                    "incident_id"
                ),
                "alarm_type": item.get(
                    "alarm_type"
                ),
                "status": status,
                "judge_verdict": item.get(
                    "judge_verdict"
                ),
                "judge_justification": (
                    item.get(
                        "judge_justification"
                    )
                ),
                "commentaire": explain_case(
                    item
                ),
            }
        )

    return cases