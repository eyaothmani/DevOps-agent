"""Incident filtering."""

from __future__ import annotations

from typing import Any

from .config import REQUIRE_JUDGE_FOR_COMPLETE
from .constants import (
    CORE_NODES_REQUIRED,
    STATUSES_EXCLUS_DASHBOARD,
)


def filter_complete_incidents(
    merged_items: list[dict[str, Any]],
    require_judge: bool = REQUIRE_JUDGE_FOR_COMPLETE,
) -> list[dict[str, Any]]:
    """Keep incidents containing all required nodes."""
    required = set(
        CORE_NODES_REQUIRED
    )

    if require_judge:
        required.add("Judge")

    return [
        item
        for item in merged_items
        if required.issubset(
            set(item.get("nodes_seen", []))
        )
    ]


def filter_by_alarm_type(
    items: list[dict[str, Any]],
    alarm_type: str | None,
) -> list[dict[str, Any]]:
    """Filter incidents by alarm type."""
    if not alarm_type:
        return items

    return [
        item
        for item in items
        if item.get("alarm_type")
        == alarm_type
    ]


def exclude_dashboard_statuses(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Exclude technical statuses from business metrics."""
    return [
        item
        for item in items
        if item.get("status")
        not in STATUSES_EXCLUS_DASHBOARD
    ]