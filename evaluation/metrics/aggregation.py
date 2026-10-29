"""Incident aggregation and DynamoDB row merging."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from .constants import (
    SKIP_FIELDS,
    SUMMED_FIELDS,
    TIMESTAMP_FIELD,
)
from .converters import (
    calculate_model_cost,
    derive_model_used,
    derive_status,
    to_float,
)
from .models import RowAccumulator


def update_incident_record(
    record: dict[str, Any],
    row: dict[str, Any],
) -> None:
    """Copy non-aggregated business fields."""
    for key, value in row.items():
        if (
            key in SKIP_FIELDS
            or key in SUMMED_FIELDS
            or key == TIMESTAMP_FIELD
        ):
            continue

        if value not in (None, ""):
            record[key] = value


def extract_row_metrics(
    row: dict[str, Any],
) -> tuple[
    float | None,
    float | None,
    str | None,
    float | None,
]:
    """Extract timestamp, tokens, model and cost."""
    timestamp = to_float(
        row.get(TIMESTAMP_FIELD)
    )

    tokens = to_float(
        row.get("tokens_used")
    )

    model = derive_model_used(row)

    cost = to_float(
        row.get("estimated_cost_usd")
    )

    return (
        timestamp,
        tokens,
        model,
        cost,
    )


def accumulate_model(
    acc: RowAccumulator,
    model: str | None,
) -> None:
    """Track models used by an incident."""
    if model:
        acc.models_used.add(model)
        acc.last_model = model


def accumulate_tokens(
    acc: RowAccumulator,
    tokens: float | None,
    model: str | None,
) -> None:
    """Aggregate token usage."""
    if tokens is None:
        return

    acc.total_tokens += tokens
    acc.has_tokens = True

    if not model:
        return

    acc.tokens_per_model[model] += tokens

    acc.calculated_cost += calculate_model_cost(
        tokens,
        model,
    )

    acc.has_calculated_cost = True


def accumulate_cost(
    acc: RowAccumulator,
    cost: float | None,
) -> None:
    """Aggregate explicit costs."""
    if cost is not None:
        acc.total_cost += cost
        acc.has_cost = True


def accumulate_row(
    acc: RowAccumulator,
    record: dict[str, Any],
    row: dict[str, Any],
) -> None:
    """Accumulate one DynamoDB row."""
    update_incident_record(
        record,
        row,
    )

    node_name = row.get("node_name")

    if node_name:
        acc.nodes_seen.add(
            str(node_name)
        )

    (
        timestamp,
        tokens,
        model,
        cost,
    ) = extract_row_metrics(row)

    if timestamp is not None:
        acc.timestamps.append(
            timestamp
        )

    accumulate_model(
        acc,
        model,
    )

    accumulate_tokens(
        acc,
        tokens,
        model,
    )

    accumulate_cost(
        acc,
        cost,
    )


def resolve_incident_cost(
    *,
    total_cost: float,
    calculated_cost: float,
    has_cost: bool,
    has_calculated_cost: bool,
) -> float | None:
    """Choose explicit cost over estimated cost."""
    if has_cost:
        return round(
            total_cost,
            6,
        )

    if has_calculated_cost:
        return round(
            calculated_cost,
            6,
        )

    return None


def add_incident_timestamps(
    record: dict[str, Any],
    timestamps: list[float],
) -> None:
    """Add normalized incident timestamps."""
    if not timestamps:
        return

    first_timestamp = min(timestamps)
    last_timestamp = max(timestamps)

    record["first_timestamp"] = (
        first_timestamp
    )

    record["last_timestamp"] = (
        last_timestamp
    )

    record["timestamp"] = (
        last_timestamp
    )

    record["alert_received_at"] = (
        datetime.fromtimestamp(
            first_timestamp,
            tz=UTC,
        ).isoformat()
    )

    record["resolved_at"] = (
        datetime.fromtimestamp(
            last_timestamp,
            tz=UTC,
        ).isoformat()
    )


def finalize_incident_record(
    record: dict[str, Any],
    acc: RowAccumulator,
    nb_rows: int,
) -> None:
    """Finalize the aggregated incident."""
    record["tokens_used"] = (
        acc.total_tokens
        if acc.has_tokens
        else None
    )

    record["estimated_cost_usd"] = (
        resolve_incident_cost(
            total_cost=acc.total_cost,
            calculated_cost=acc.calculated_cost,
            has_cost=acc.has_cost,
            has_calculated_cost=(
                acc.has_calculated_cost
            ),
        )
    )

    record["nb_node_writes"] = nb_rows

    record["nodes_seen"] = sorted(
        acc.nodes_seen
    )

    record["models_used"] = sorted(
        acc.models_used
    )

    record["tokens_par_model"] = (
        dict(acc.tokens_per_model)
        if acc.tokens_per_model
        else {}
    )

    record["model_used"] = (
        acc.last_model
    )

    add_incident_timestamps(
        record,
        acc.timestamps,
    )

    record["status"] = (
        derive_status(record)
        or "UNKNOWN"
    )


def merge_incident_rows(
    incident_id: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge all DynamoDB rows for one incident."""
    rows_sorted = sorted(
        rows,
        key=lambda row: str(
            row.get("node_timestamp", "")
        ),
    )

    record: dict[str, Any] = {
        "incident_id": incident_id
    }

    accumulator = RowAccumulator()

    for row in rows_sorted:
        accumulate_row(
            accumulator,
            record,
            row,
        )

    finalize_incident_record(
        record,
        accumulator,
        len(rows_sorted),
    )

    return record


def merge_items_by_incident(
    raw_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge DynamoDB writes by incident ID."""
    grouped: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for item in raw_items:
        incident_id = item.get(
            "incident_id"
        )

        if incident_id is not None:
            grouped[str(incident_id)].append(
                item
            )

    return [
        merge_incident_rows(
            incident_id,
            rows,
        )
        for incident_id, rows in grouped.items()
    ]