"""Commande --list-values : distribution des valeurs d'un champ."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .. import config
from ..dynamo import scan_all


def cmd_list_values(table: Any, field: str) -> None:
    """Exécute --list-values."""
    if not field.strip():
        raise SystemExit("--list-values requiert un nom de champ non vide")

    if config.SENSITIVE_KEY_RE.search(field):
        raise SystemExit(
            f"'{field}' semble être un champ sensible — listage des valeurs refusé."
        )

    raw = scan_all(table)

    counts: dict[str, int] = defaultdict(int)
    missing = 0

    for row in raw:
        value = row.get(field)

        if value in (None, ""):
            missing += 1
            continue

        counts[str(value)] += 1

    print(f"Champ '{field}' — {len(raw)} lignes brutes scannées")
    print(f"Valeurs distinctes : {len(counts)}  |  Lignes sans ce champ : {missing}\n")

    for value, count in sorted(counts.items(), key=lambda item: -item[1]):
        print(f"  {value:<45} : {count}")