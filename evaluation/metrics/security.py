"""Security and guardrail metrics."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .constants import (
    FAILURE_STATUSES,
    GUARDRAIL_TRIGGER_STATUSES,
)


def metriques_securite(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate guardrail metrics."""
    if not items:
        return {
            "nb_garde_fous_declenches": 0,
            "taux_garde_fous": 0.0,
            "details": {},
        }

    guardrails = [
        item
        for item in items
        if item.get(
            "status"
        ) in GUARDRAIL_TRIGGER_STATUSES
    ]

    details: dict[
        str,
        int,
    ] = defaultdict(int)

    for item in guardrails:
        status = str(
            item.get("status")
        )
        details[status] += 1

    return {
        "nb_garde_fous_declenches": len(
            guardrails
        ),
        "taux_garde_fous": round(
            len(guardrails)
            / len(items),
            4,
        ),
        "details": dict(details),
    }


def metriques_bugs_techniques(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate infrastructure failures."""
    if not items:
        return {
            "nb_bugs_techniques": 0,
            "taux_bugs_techniques": 0.0,
            "details": {},
        }

    bugs = [
        item
        for item in items
        if item.get(
            "status"
        ) in FAILURE_STATUSES
    ]

    details: dict[
        str,
        int,
    ] = defaultdict(int)

    for item in bugs:
        status = str(
            item.get("status")
        )
        details[status] += 1

    return {
        "nb_bugs_techniques": len(
            bugs
        ),
        "taux_bugs_techniques": round(
            len(bugs)
            / len(items),
            4,
        ),
        "details": dict(details),
    }