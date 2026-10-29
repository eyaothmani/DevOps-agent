"""Commande --export-golden : export d'un golden dataset pour l'évaluation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .. import config
from ..audit_trail import audit
from ..dynamo import scan_all
from ..merge import merge_items_by_incident
from ..transform import clean_decimals, redact_sensitive
from ..validators import safe_output_path


def _is_complete_incident(item: dict[str, Any]) -> bool:
    """Vérifie que tous les champs obligatoires sont présents."""
    required_fields = [
        field
        for field, expectation in config.FIELD_EXPECTATIONS.items()
        if expectation == "always"
    ]

    return all(item.get(field) not in (None, "") for field in required_fields)


def _prepare_golden_items(
    merged: list[dict[str, Any]], reveal_sensitive: bool
) -> list[dict[str, Any]]:
    """Prépare les incidents pour l'export."""
    complete = [item for item in merged if _is_complete_incident(item)]

    clean_items = [clean_decimals(item) for item in complete]

    if not reveal_sensitive:
        clean_items = [redact_sensitive(item) for item in clean_items]

    clean_items.sort(key=lambda item: str(item.get("timestamp", "")))

    return clean_items


def _write_golden_dataset(path: Path, items: list[dict[str, Any]]) -> None:
    """Écrit le golden dataset avec permissions restreintes."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(items, file, ensure_ascii=False, indent=2)

    try:
        os.chmod(path, 0o600)
    except OSError:
        config.logger.warning("Impossible de restreindre les permissions de %s", path)


def cmd_export_golden(table: Any, output_path: Path, reveal_sensitive: bool) -> None:
    """Exécute --export-golden."""
    safe_path = safe_output_path(output_path)

    raw = scan_all(table)
    merged = merge_items_by_incident(raw)

    clean_items = _prepare_golden_items(merged, reveal_sensitive)

    if not clean_items:
        print(
            "Aucun incident complet "
            "(champs 'always' tous remplis) "
            "— impossible d'exporter."
        )
        print("Lance --inspect pour voir quels champs manquent.")
        return

    _write_golden_dataset(safe_path, clean_items)

    print(
        f"{len(clean_items)} incidents RÉELS "
        f"(fusionnés, complets) exportés vers "
        f"{safe_path}"
    )

    if not reveal_sensitive:
        print(
            "(champs sensibles masqués dans l'export — "
            "utiliser --reveal-sensitive sinon)"
        )

    print("Types d'alarme :", sorted({item.get("alarm_type") for item in clean_items}))

    print("Statuts        :", sorted({item.get("status") for item in clean_items}))

    skipped = len(merged) - len(clean_items)

    if skipped:
        print(f"({skipped} incidents incomplets exclus — voir --inspect)")

    audit("EXPORT_GOLDEN", f"{len(clean_items)} incidents -> {safe_path}")