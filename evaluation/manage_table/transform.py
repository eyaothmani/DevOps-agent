"""
Conversion et sécurisation des valeurs issues de DynamoDB.

Fonctions pures : conversion des `Decimal`, masquage des champs
sensibles avant affichage/export, et parsing de timestamps hétérogènes
(Unix epoch ou ISO 8601).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from . import config


def clean_decimals(obj: Any) -> Any:
    """Convertit récursivement les Decimal DynamoDB."""
    if isinstance(obj, list):
        return [clean_decimals(value) for value in obj]

    if isinstance(obj, dict):
        return {key: clean_decimals(value) for key, value in obj.items()}

    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)

    return obj


def redact_sensitive(obj: Any) -> Any:
    """Masque récursivement les champs sensibles avant affichage/export."""
    if isinstance(obj, list):
        return [redact_sensitive(value) for value in obj]

    if not isinstance(obj, dict):
        return obj

    result: dict[Any, Any] = {}

    for key, value in obj.items():
        if isinstance(key, str) and config.SENSITIVE_KEY_RE.search(key):
            result[key] = "***REDACTED***"
        else:
            result[key] = redact_sensitive(value)

    return result


def to_float(value: Any) -> float | None:
    """Convertit une valeur en float."""
    if isinstance(value, Decimal):
        value = float(value)

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_any_ts(value: Any) -> datetime | None:
    """Convertit un timestamp Unix ou ISO en datetime UTC."""
    if value is None:
        return None

    if isinstance(value, Decimal):
        value = float(value)

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (ValueError, OSError, OverflowError):
            return None

    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None