"""Quality and AI evaluation metrics."""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from .converters import to_float


def groundedness_moyen(
    items: list[dict[str, Any]],
) -> float:
    """Calculate average groundedness."""
    scores = [
        score
        for score in (
            to_float(
                item.get(
                    "groundedness_score"
                )
            )
            for item in items
        )
        if score is not None
    ]

    if not scores:
        return 0.0

    return round(
        statistics.mean(scores),
        4,
    )


def groundedness_par_type(
    items: list[dict[str, Any]],
) -> dict[str, float]:
    """Calculate groundedness by alarm type."""
    buckets: dict[
        str,
        list[float],
    ] = defaultdict(list)

    for item in items:
        score = to_float(
            item.get(
                "groundedness_score"
            )
        )

        if score is None:
            continue

        alarm_type = item.get(
            "alarm_type",
            "UNKNOWN",
        )

        buckets[str(alarm_type)].append(
            score
        )

    return {
        key: round(
            statistics.mean(values),
            4,
        )
        for key, values in buckets.items()
    }


def taux_accord_juge(
    items: list[dict[str, Any]],
) -> float:
    """Calculate Judge agreement rate."""
    comparable = [
        item
        for item in items
        if item.get(
            "judge_verdict"
        )
        is not None
    ]

    if not comparable:
        return 0.0

    agreements = sum(
        1
        for item in comparable
        if str(
            item["judge_verdict"]
        ).lower()
        == "coherent"
    )

    return round(
        agreements / len(comparable),
        4,
    )


def taux_calibration_confiance(
    items: list[dict[str, Any]],
) -> float | None:
    """Compare confidence score against Judge verdict."""
    comparable = [
        item
        for item in items
        if (
            item.get(
                "judge_verdict"
            )
            is not None
            and to_float(
                item.get("confidence")
            )
            is not None
        )
    ]

    if not comparable:
        return None

    agreements = 0

    for item in comparable:
        confidence = to_float(
            item["confidence"]
        )

        if confidence is None:
            continue

        verdict = str(
            item["judge_verdict"]
        ).lower()

        confidence_ok = (
            confidence >= 85
        )

        judge_ok = (
            verdict == "coherent"
        )

        if confidence_ok == judge_ok:
            agreements += 1

    return round(
        agreements / len(comparable),
        4,
    )