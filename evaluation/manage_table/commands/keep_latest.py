"""Commande --keep-latest : ne conserve que les N incidents les plus récents."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..dynamo import scan_all
from ..merge import merge_items_by_incident
from ..transform import parse_any_ts
from .delete_rows import delete_rows


def _incident_timestamp(record: dict[str, Any]) -> datetime:
    """Retourne le timestamp de référence d'un incident."""
    timestamp = parse_any_ts(record.get("timestamp") or record.get("alert_received_at"))

    return timestamp or datetime.min.replace(tzinfo=UTC)


def _latest_incident_ids(merged: list[dict[str, Any]], n: int) -> set[str]:
    """Retourne les N incidents les plus récents."""
    sorted_items = sorted(merged, key=_incident_timestamp, reverse=True)

    return {str(item["incident_id"]) for item in sorted_items[:n]}


def cmd_keep_latest(table: Any, n: int, dry_run: bool) -> None:
    """Exécute --keep-latest."""
    raw = scan_all(table)
    merged = merge_items_by_incident(raw)

    keep_ids = _latest_incident_ids(merged, n)

    print(
        f"Incidents totaux : {len(merged)} -> "
        f"on garde les {min(n, len(merged))} plus récents"
    )

    to_delete_rows = [row for row in raw if str(row.get("incident_id")) not in keep_ids]

    delete_rows(
        table,
        to_delete_rows,
        dry_run,
        f"Suppression des incidents hors top-{n}",
        total_in_table=len(raw),
    )