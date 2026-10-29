"""Validateurs partagés pour les arguments CLI et les chemins de sortie."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from . import config

TABLE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,255}$")


def validate_table_name(table_name: str) -> str:
    """Valide le nom de table DynamoDB."""
    if not TABLE_NAME_RE.fullmatch(table_name):
        raise ValueError(
            f"Nom de table DynamoDB invalide : {table_name!r}. "
            "Le nom doit contenir uniquement des lettres, chiffres, "
            "underscore (_), point (.) ou tiret (-), avec 3 à 255 caractères."
        )

    return table_name


def safe_output_path(raw_path: Path) -> Path:
    """Empêche l'écriture en dehors du projet."""
    resolved = raw_path.expanduser().resolve()

    try:
        resolved.relative_to(config.OUTPUT_ROOT)
    except ValueError as exc:
        raise SystemExit(
            f"--output doit rester sous {config.OUTPUT_ROOT} "
            f"(reçu : {resolved})"
        ) from exc

    return resolved


def positive_int(raw: str) -> int:
    """Valide un entier strictement positif."""
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "doit être un entier"
        ) from exc

    if value <= 0:
        raise argparse.ArgumentTypeError(
            "doit être un entier strictement positif"
        )

    return value
