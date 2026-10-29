"""Commande --schema : inventaire des champs écrits par chaque node."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from .. import config
from ..dynamo import scan_all
from ..transform import clean_decimals


def _field_example_str(field: str, example: Any) -> str:
    """Formate un exemple sans exposer les champs sensibles."""
    if config.SENSITIVE_KEY_RE.search(field):
        return "***REDACTED***"

    example = clean_decimals(example)

    if isinstance(example, str):
        result = example
    else:
        result = json.dumps(example, ensure_ascii=False)

    if len(result) > 50:
        result = result[:47] + "..."

    return result


def _build_node_field_report(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, Any]]:
    """Construit les statistiques des champs d'un node."""
    field_count: dict[str, int] = defaultdict(int)
    field_example: dict[str, Any] = {}

    for row in rows:
        for key, value in row.items():
            if value in (None, ""):
                continue

            field_count[key] += 1

            if key not in field_example:
                field_example[key] = value

    return field_count, field_example


def _print_node_field_report(node: str, rows: list[dict[str, Any]]) -> None:
    """Affiche le rapport des champs d'un node."""
    print("=" * 78)
    print(f"NODE : {node}  ({len(rows)} lignes)")
    print("=" * 78)

    field_count, field_example = _build_node_field_report(rows)

    total = len(rows)

    width = max((len(field) for field in field_count), default=10)

    for field in sorted(field_count, key=lambda name: -field_count[name]):
        present = field_count[field]
        pct = 100 * present / total if total else 0

        example = _field_example_str(field, field_example[field])

        print(
            f"  {field:<{width}} : "
            f"{present:4d}/{total:<4d} "
            f"({pct:5.1f}%)  ex: {example}"
        )

    print()


def _print_missing_expected_fields(by_node: dict[str, list[dict[str, Any]]]) -> None:
    """Affiche les champs attendus mais absents."""
    print("=" * 78)
    print("Champs attendus par evaluation/metrics.py mais absents de TOUS les nodes:")
    print("(status/model_used peuvent être dérivables)")
    print("=" * 78)

    all_fields_seen = {
        field for rows in by_node.values() for row in rows for field in row
    }

    missing = [
        field for field in config.FIELD_EXPECTATIONS if field not in all_fields_seen
    ]

    if not missing:
        print("  (aucun — tous les champs attendus existent quelque part)")
        return

    for field in missing:
        print(f"  - {field}")


def cmd_schema(table: Any) -> None:
    """Exécute --schema."""
    raw = scan_all(table)

    by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in raw:
        node = row.get("node_name", "(sans node_name)")

        by_node[str(node)].append(row)

    print(f"Lignes brutes scannées : {len(raw)}")
    print(f"Nodes distincts trouvés : {sorted(by_node.keys())}\n")

    for node, rows in sorted(by_node.items()):
        _print_node_field_report(node, rows)

    _print_missing_expected_fields(by_node)