"""
Fusion des écritures DynamoDB (une ligne par node du graphe) en un seul
enregistrement par incident.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import config
from .derive import derive_model_used, derive_status
from .transform import to_float


def _group_items_by_incident(
    raw_items: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Regroupe les écritures par incident."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for item in raw_items:
        incident_id = item.get("incident_id")

        if incident_id is not None:
            grouped[str(incident_id)].append(item)

    return grouped


def _merge_row_fields(record: dict[str, Any], row: dict[str, Any]) -> None:
    """Copie les champs non agrégés d'une ligne."""
    for key, value in row.items():
        if key in config.SKIP_FIELDS:
            continue

        if key in config.SUMMED_FIELDS:
            continue

        if value not in (None, ""):
            record[key] = value


def _merge_incident_rows(incident_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Fusionne toutes les lignes d'un incident."""
    rows_sorted = sorted(rows, key=lambda row: str(row.get("node_timestamp", "")))

    record: dict[str, Any] = {"incident_id": incident_id}

    total_tokens = 0.0
    total_cost = 0.0

    has_tokens = False
    has_cost = False

    for row in rows_sorted:
        _merge_row_fields(record, row)

        tokens = to_float(row.get("tokens_used"))
        cost = to_float(row.get("estimated_cost_usd"))

        if tokens is not None:
            total_tokens += tokens
            has_tokens = True

        if cost is not None:
            total_cost += cost
            has_cost = True

    record["tokens_used"] = total_tokens if has_tokens else None

    record["estimated_cost_usd"] = round(total_cost, 6) if has_cost else None

    record["nb_node_writes"] = len(rows_sorted)

    record["status"] = derive_status(record)
    record["model_used"] = derive_model_used(record)

    return record


def merge_items_by_incident(raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fusionne les écritures DynamoDB par incident."""
    grouped = _group_items_by_incident(raw_items)

    return [
        _merge_incident_rows(incident_id, rows) for incident_id, rows in grouped.items()
    ]