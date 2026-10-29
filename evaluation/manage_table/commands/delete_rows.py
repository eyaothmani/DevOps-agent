"""
Helpers de suppression partagés par les commandes destructives
(--purge et --keep-latest) : confirmation interactive, suppression
d'une ligne, et boucle de suppression avec journal d'audit.
"""

from __future__ import annotations

import sys
from typing import Any

from botocore.exceptions import ClientError

from .. import config
from ..audit_trail import audit
from ..dynamo import key_from_item


def confirm_destructive(rows: list[dict[str, Any]], total_in_table: int, label: str) -> bool:
    """Demande une confirmation avant suppression."""
    if not sys.stdin.isatty():
        print(
            "Entrée non interactive détectée : "
            "les opérations destructives nécessitent "
            "une confirmation manuelle. "
            "Utilise --dry-run pour prévisualiser."
        )
        return False

    ratio = len(rows) / total_in_table if total_in_table else 0

    if ratio >= config.DESTRUCTIVE_RATIO_CONFIRM_THRESHOLD:
        return _confirm_major_deletion(rows, total_in_table, label)

    return _confirm_normal_deletion(rows)


def _confirm_major_deletion(
    rows: list[dict[str, Any]], total_in_table: int, label: str
) -> bool:
    """Confirmation renforcée pour une suppression majeure."""
    print(
        f"\n/!\\ Cette opération ({label}) va supprimer "
        f"{len(rows)}/{total_in_table} lignes "
        f"({len(rows) / total_in_table * 100:.0f}%) "
        f"de la table '{config.TABLE_NAME}'."
    )

    typed = input(
        f"Tape le nom exact de la table pour confirmer ('{config.TABLE_NAME}') : "
    )

    return typed.strip() == config.TABLE_NAME


def _confirm_normal_deletion(rows: list[dict[str, Any]]) -> bool:
    """Confirmation pour une suppression normale."""
    confirm = input(f"Confirmer la suppression de {len(rows)} lignes ? Tape 'oui' : ")

    return confirm.strip().lower() == "oui"


def _log_delete_error(exc: ClientError, key: dict[str, Any]) -> None:
    """Journalise une erreur de suppression."""
    code = exc.response.get("Error", {}).get("Code", "Unknown")

    if code in ("AccessDeniedException", "UnrecognizedClientException"):
        config.logger.exception("Accès refusé pour supprimer %s", key)
        return

    config.logger.exception("Erreur DynamoDB (%s) pour %s", code, key)


def delete_one_row(
    table: Any, row: dict[str, Any], deleted: int, errors: int
) -> tuple[int, int]:
    """Supprime une ligne."""
    try:
        key = key_from_item(table, row)
    except KeyError as exc:
        config.logger.warning("Skip (clé absente) : %s", exc)
        return deleted, errors + 1

    try:
        table.delete_item(Key=key)
        return deleted + 1, errors
    except ClientError as exc:
        _log_delete_error(exc, key)
        return deleted, errors + 1


def _print_delete_preview(rows: list[dict[str, Any]]) -> None:
    """Affiche l'aperçu d'une suppression."""
    for row in rows[:10]:
        print(f"  - {row.get('incident_id')} / {row.get('node_timestamp')}")

    if len(rows) > 10:
        print(f"  ... et {len(rows) - 10} de plus.")


def delete_rows(
    table: Any,
    rows: list[dict[str, Any]],
    dry_run: bool,
    label: str,
    total_in_table: int,
) -> None:
    """Supprime une liste de lignes avec confirmation."""
    print(f"{label} : {len(rows)} lignes concernées")

    if dry_run:
        print("[DRY-RUN] Rien supprimé. Relance sans --dry-run pour appliquer.")
        _print_delete_preview(rows)
        return

    if not rows:
        print("Rien à supprimer.")
        return

    if not confirm_destructive(rows, total_in_table, label):
        print("Annulé.")
        return

    audit("DELETE_START", f"{label} — {len(rows)} lignes ciblées")

    deleted = 0
    errors = 0
    total = len(rows)

    for index, row in enumerate(rows, 1):
        deleted, errors = delete_one_row(table, row, deleted, errors)

        if index % 100 == 0 or index == total:
            print(f"  ... {index}/{total} traités")

    print(f"{deleted} lignes supprimées, {errors} erreurs.")

    audit("DELETE_DONE", f"{label} — deleted={deleted} errors={errors}")