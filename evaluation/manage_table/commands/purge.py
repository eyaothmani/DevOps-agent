"""Commande --purge : suppression des incidents antérieurs à une date."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..dynamo import scan_all
from ..transform import parse_any_ts
from .delete_rows import delete_rows


def _rows_before_cutoff(
    raw: list[dict[str, Any]], cutoff: datetime
) -> list[dict[str, Any]]:
    """Retourne les lignes antérieures à une date."""
    default_time = datetime.min.replace(tzinfo=UTC)

    result: list[dict[str, Any]] = []

    for row in raw:
        timestamp = parse_any_ts(row.get("timestamp")) or default_time

        if timestamp < cutoff:
            result.append(row)

    return result


def cmd_purge(table: Any, keep_after: str | None, dry_run: bool) -> None:
    """Exécute --purge."""
    raw = scan_all(table)

    cutoff = parse_any_ts(keep_after) if keep_after else None

    if cutoff is None:
        to_delete = raw
    else:
        to_delete = _rows_before_cutoff(raw, cutoff)

    delete_rows(table, to_delete, dry_run, "Purge", total_in_table=len(raw))