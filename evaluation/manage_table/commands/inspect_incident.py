"""Commande --inspect-incident : détail brut d'un incident donné."""

from __future__ import annotations

from typing import Any

import boto3.dynamodb.conditions as ddb_cond

from .inspect_table import display_json


def _query_incident_rows(table: Any, incident_id: str) -> list[dict[str, Any]]:
    """Récupère les lignes d'un incident."""
    response = table.query(
        KeyConditionExpression=(ddb_cond.Key("incident_id").eq(incident_id))
    )

    rows = response.get("Items", [])

    return sorted(rows, key=lambda row: str(row.get("node_timestamp", "")))


def cmd_inspect_incident(table: Any, incident_id: str, reveal_sensitive: bool) -> None:
    """Exécute --inspect-incident."""
    rows = _query_incident_rows(table, incident_id)

    print(f"Incident '{incident_id}' : {len(rows)} lignes\n")

    for index, row in enumerate(rows, 1):
        print(f"--- Ligne {index} (node_timestamp={row.get('node_timestamp')}) ---")

        display_json(row, reveal_sensitive)

        print()