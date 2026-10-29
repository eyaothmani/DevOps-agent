"""Conversion and normalization helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from .config import PRICE_PER_TOKEN


def to_float(value: Any) -> float | None:
    """Convert a value to float safely."""
    if isinstance(value, Decimal):
        value = float(value)

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def derive_status(record: dict[str, Any]) -> str | None:
    """Derive the final incident status."""
    status = record.get("decision_status")

    if status:
        return str(status)

    communication_status = record.get(
        "communication_status"
    )

    if communication_status:
        return str(communication_status)

    return None


def derive_model_used(
    record: dict[str, Any],
) -> str | None:
    """Normalize the Bedrock model identifier."""
    model_id = record.get("model_id")

    if not model_id:
        return None

    model = str(model_id).lower()

    if "haiku" in model:
        return "haiku"

    if "sonnet" in model:
        return "sonnet"

    if "opus" in model:
        return "opus"

    return str(model_id)


def parse_timestamp(
    value: Any,
) -> datetime | None:
    """Convert Unix or ISO timestamp to UTC."""
    if value is None:
        return None

    if isinstance(value, (int, float, Decimal)):
        try:
            return datetime.fromtimestamp(
                float(value),
                tz=UTC,
            )
        except (
            ValueError,
            OSError,
            OverflowError,
        ):
            return None

    if isinstance(value, str):
        try:
            normalized = value.replace(
                "Z",
                "+00:00",
            )

            parsed = datetime.fromisoformat(
                normalized
            )

            if parsed.tzinfo is None:
                parsed = parsed.replace(
                    tzinfo=UTC
                )

            return parsed.astimezone(UTC)

        except ValueError:
            return None

    return None
def _has_minimum_node_writes(item: dict[str, Any]) -> bool:
    """Return whether an incident has at least two node writes."""
    try:
        nb_node_writes = int(item.get("nb_node_writes", 0))
    except (TypeError, ValueError):
        return False
    return nb_node_writes >= 2


def _non_negative_delta(end, start) -> float | None:
    """Return the delta in seconds between two datetimes, or None if negative."""
    delta = (end - start).total_seconds()
    return delta if delta >= 0 else None


def _delta_from_raw_timestamps(first_timestamp, last_timestamp) -> float | None:
    """Compute a delta in seconds from raw epoch-like timestamp values."""
    try:
        delta = float(last_timestamp) - float(first_timestamp)
    except (TypeError, ValueError):
        return None
    return delta if delta >= 0 else None


def _resolution_seconds_fallback(
    item: dict[str, Any],
    start,
) -> float | None:
    """Fallback resolution calculation when alert/resolved timestamps are missing."""
    first_timestamp = item.get("first_timestamp")
    last_timestamp = item.get("last_timestamp")

    if first_timestamp is not None and last_timestamp is not None:
        return _delta_from_raw_timestamps(first_timestamp, last_timestamp)

    if start is not None:
        action_completed_at = parse_timestamp(item.get("action_completed_at"))
        if action_completed_at is not None:
            return _non_negative_delta(action_completed_at, start)

    return None


def resolution_seconds(
    item: dict[str, Any],
) -> float | None:
    """
    Calculate incident resolution duration in seconds.
    Requires at least two node writes.
    """
    if not _has_minimum_node_writes(item):
        return None

    start = parse_timestamp(item.get("alert_received_at"))
    end = parse_timestamp(item.get("resolved_at"))

    if start is not None and end is not None:
        return _non_negative_delta(end, start)

    return _resolution_seconds_fallback(item, start)

def calculate_model_cost(
    tokens: float,
    model: str,
) -> float:
    """Estimate model cost from token consumption."""
    price = PRICE_PER_TOKEN.get(
        model,
        PRICE_PER_TOKEN["default"],
    )

    return tokens * price