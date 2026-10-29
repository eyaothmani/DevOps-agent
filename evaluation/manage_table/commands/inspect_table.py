"""Commande --inspect : complétude des champs et exemple d'incident."""

from __future__ import annotations

import json
from typing import Any

from .. import config
from ..dynamo import scan_all
from ..merge import merge_items_by_incident
from ..transform import clean_decimals, redact_sensitive


def _field_verdict(pct: float, expectation: str) -> str:
    """Détermine le verdict de complétude d'un champ."""
    if pct == 0:
        return "STRUCTUREL — jamais écrit nulle part, à corriger côté agent"

    if expectation == "always" and pct < 95:
        return (
            f"PARTIEL — attendu à 100%, "
            f"seulement {pct:.0f}% -> vérifier le node concerné"
        )

    if expectation == "sometimes":
        return "NORMAL — présence partielle attendue (cas métier)"

    return "COMPLET"


def _build_field_report(
    merged: list[dict[str, Any]],
) -> list[tuple[str, int, int, float, str]]:
    """Construit les lignes du rapport de complétude."""
    total = len(merged) or 1
    report: list[tuple[str, int, int, float, str]] = []

    for field, expectation in config.FIELD_EXPECTATIONS.items():
        present = sum(1 for item in merged if item.get(field) not in (None, ""))

        pct = 100 * present / total

        report.append((field, present, total, pct, _field_verdict(pct, expectation)))

    return report


def _print_field_completeness_report(merged: list[dict[str, Any]]) -> None:
    """Affiche le rapport de complétude."""
    print("\n" + "=" * 78)
    print("Complétude des champs — calculée sur les INCIDENTS FUSIONNÉS")
    print("(un champ à 0% = vraiment jamais écrit par aucun node)")
    print("=" * 78)

    rows_report = _build_field_report(merged)

    width = max(len(row[0]) for row in rows_report)

    for field, present, total, pct, verdict in rows_report:
        print(f"  {field:<{width}} : {present:4d}/{total:<4d} ({pct:5.1f}%)  {verdict}")

    structural = [row[0] for row in rows_report if row[3] == 0]

    if structural:
        print(
            "\nChamps à corriger en priorité côté code agent "
            f"(jamais écrits) : {structural}"
        )
    else:
        print(
            "\nAucun champ structurellement absent — tous sont au moins écrits parfois."
        )


def display_json(value: Any, reveal_sensitive: bool) -> None:
    """Affiche un objet JSON en appliquant le masquage."""
    display = clean_decimals(value)

    if not reveal_sensitive:
        display = redact_sensitive(display)

    print(json.dumps(display, indent=2, ensure_ascii=False))


def _print_sample_incident(
    raw: list[dict[str, Any]], merged: list[dict[str, Any]], reveal_sensitive: bool
) -> None:
    """Affiche l'incident le plus complet."""
    if not merged:
        return

    sample = max(merged, key=lambda item: item.get("nb_node_writes", 0))

    sample_id = sample["incident_id"]

    print("\n" + "=" * 78)
    print(f"Exemple — incident '{sample_id}' ({sample.get('nb_node_writes')} lignes)")

    if not reveal_sensitive:
        print(
            "(champs sensibles masqués — utiliser --reveal-sensitive pour les afficher)"
        )

    print("=" * 78)

    rows = [row for row in raw if row.get("incident_id") == sample_id]

    rows.sort(key=lambda row: str(row.get("node_timestamp", "")))

    for row in rows:
        display_json(row, reveal_sensitive)
        print()

    print("--- Fusionné ---")

    display_json(sample, reveal_sensitive)


def cmd_inspect(table: Any, reveal_sensitive: bool) -> None:
    """Exécute --inspect."""
    print(f"Table : {table.table_name}")
    print(f"Key schema : {table.key_schema}\n")

    raw = scan_all(table)
    merged = merge_items_by_incident(raw)

    print(f"Lignes brutes scannées      : {len(raw)}")
    print(f"Incidents distincts (fusionnés) : {len(merged)}")

    if merged:
        print(f"Moyenne de lignes / incident : {len(raw) / len(merged):.2f}")

    _print_field_completeness_report(merged)

    _print_sample_incident(raw, merged, reveal_sensitive)