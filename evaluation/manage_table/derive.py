"""Dérivation de champs métier à partir d'un enregistrement fusionné."""

from __future__ import annotations

from typing import Any


def derive_status(record: dict[str, Any]) -> Any:
    """Déduit le statut final."""
    return record.get("decision_status") or record.get("communication_status")


def derive_model_used(record: dict[str, Any]) -> Any:
    """Normalise le modèle utilisé."""
    model_id = record.get("model_id")

    if not model_id:
        return None

    model = str(model_id).lower()

    if "haiku" in model:
        return "haiku"

    if "sonnet" in model:
        return "sonnet"

    if "opus" in model:
        return "opus"

    return str(model_id)