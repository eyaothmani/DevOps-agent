"""Cost and token metrics."""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from .converters import to_float


def cout_total_par_incident(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate total and average cost."""
    costs = [
        cost
        for cost in (
            to_float(
                item.get(
                    "estimated_cost_usd"
                )
            )
            for item in items
        )
        if cost is not None
    ]

    if not costs:
        return {
            "cout_moyen_par_incident_usd": 0.0,
            "cout_total_usd": 0.0,
            "nb_incidents_avec_cout": 0,
        }

    return {
        "cout_moyen_par_incident_usd": round(
            statistics.mean(costs),
            6,
        ),
        "cout_total_usd": round(
            sum(costs),
            6,
        ),
        "nb_incidents_avec_cout": len(
            costs
        ),
    }


def repartition_tokens_par_model(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate token consumption by model."""
    totals: dict[
        str,
        float,
    ] = defaultdict(float)

    multi_model_count = 0

    for item in items:
        tokens_per_model = (
            item.get(
                "tokens_par_model"
            )
            or {}
        )

        for model, tokens in (
            tokens_per_model.items()
        ):
            numeric_tokens = to_float(
                tokens
            )

            if numeric_tokens is not None:
                totals[str(model)] += (
                    numeric_tokens
                )

        if len(
            item.get(
                "models_used"
            )
            or []
        ) > 1:
            multi_model_count += 1

    return {
        "tokens_par_model": {
            key: round(
                value,
                2,
            )
            for key, value in totals.items()
        },
        "nb_incidents_multi_modeles": (
            multi_model_count
        ),
    }