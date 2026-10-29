"""
Configuration centrale de l'outil manage_table.

Regroupe : logging, chemins par défaut, constantes de validation et
attentes de champs (utilisées par les commandes --inspect / --schema /
--export-golden). Aucune logique métier ici — uniquement des constantes
et des validateurs purs.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger("manage_table")

AUDIT_LOG_PATH = Path(__file__).parent / "manage_table_audit.log"

TABLE_NAME = os.getenv("AGENT_DECISIONS_TABLE", "agent_decisions")

# Défense en profondeur : validation du nom de table.
# DynamoDB autorise notamment les lettres, chiffres, underscore, point
# et tiret dans les noms de tables.
_TABLE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,255}$")


def validate_table_name(table_name: str) -> str:
    """Valide le nom de table DynamoDB."""
    if not _TABLE_NAME_RE.fullmatch(table_name):
        raise ValueError(
            "Nom de table DynamoDB invalide : "
            f"{table_name!r}. "
            "Le nom doit contenir uniquement des lettres, chiffres, "
            "underscore (_), point (.) ou tiret (-), avec 3 à 255 caractères."
        )

    return table_name


# ---------------------------------------------------------------------------
# Configuration des champs
# ---------------------------------------------------------------------------

FIELD_EXPECTATIONS: dict[str, str] = {
    "incident_id": "always",
    "alarm_type": "always",
    "timestamp": "always",
    "status": "always",
    "confidence": "always",
    "model_used": "always",
    "groundedness_score": "always",
    "judge_verdict": "sometimes",
    "resolved_at": "sometimes",
    "action_completed_at": "sometimes",
    "tokens_used": "always",
    "estimated_cost_usd": "always",
}

SUMMED_FIELDS = {"tokens_used", "estimated_cost_usd"}

SKIP_FIELDS = {"incident_id", "node_timestamp"}

SENSITIVE_KEY_RE = re.compile(
    r"(secret|token|password|passwd|api[-_]?key|"
    r"signing[-_]?key|webhook|credential|authoriz|private[-_]?key)",
    re.IGNORECASE,
)

DEFAULT_GOLDEN_PATH = Path(__file__).parent.parent / "evaluation" / "golden_dataset.json"

OUTPUT_ROOT = Path(__file__).parent.parent.resolve()

DESTRUCTIVE_RATIO_CONFIRM_THRESHOLD = 0.9