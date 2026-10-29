"""Metrics evaluation package."""

from __future__ import annotations

from typing import Any

from .aggregation import merge_items_by_incident
from .config import GOLDEN_DATASET_PATH, PRICE_PER_TOKEN
from .converters import (
    derive_model_used as _derive_model_used,
)
from .converters import (
    derive_status as _derive_status,
)
from .converters import (
    parse_timestamp as _parse_ts,
)
from .converters import (
    to_float as _to_float,
)
from .costs import cout_total_par_incident, repartition_tokens_par_model
from .filters import filter_complete_incidents
from .loaders import (
    load_from_dynamodb as _load_from_dynamodb,
)
from .loaders import (
    load_from_golden_dataset as _load_from_golden_dataset,
)
from .mttr import compute_metrics, get_incidents
from .performance import (
    _resolution_seconds,
    mttr_par_type,
    taux_escalade_humaine,
    taux_succes_execution,
)
from .quality import (
    groundedness_moyen,
    groundedness_par_type,
    taux_accord_juge,
    taux_calibration_confiance,
)
from .reliability import (
    cas_echec_documentes,
    status_repartition,
)
from .reliability import (
    explain_case as _explique_cas,
)
from .security import metriques_bugs_techniques, metriques_securite


def load_decisions(
    mode: str = "offline",
) -> list[dict[str, Any]]:
    """Package-level wrapper — respecte le monkeypatch sur _load_from_*."""
    normalized_mode = mode.lower()

    if normalized_mode == "offline":
        return _load_from_golden_dataset()

    if normalized_mode == "live":
        return _load_from_dynamodb()

    if normalized_mode == "auto":
        if GOLDEN_DATASET_PATH.exists():
            return _load_from_golden_dataset()

        return _load_from_dynamodb()

    raise ValueError(f"Unsupported metrics mode: {mode}")


__all__ = [
    "GOLDEN_DATASET_PATH",
    "PRICE_PER_TOKEN",
    "_derive_model_used",
    "_derive_status",
    "_explique_cas",
    "_load_from_dynamodb",
    "_load_from_golden_dataset",
    "_parse_ts",
    "_resolution_seconds",
    "_to_float",
    "cas_echec_documentes",
    "compute_metrics",
    "cout_total_par_incident",
    "filter_complete_incidents",
    "get_incidents",
    "groundedness_moyen",
    "groundedness_par_type",
    "load_decisions",
    "merge_items_by_incident",
    "metriques_bugs_techniques",
    "metriques_securite",
    "mttr_par_type",
    "repartition_tokens_par_model",
    "status_repartition",
    "taux_accord_juge",
    "taux_calibration_confiance",
    "taux_escalade_humaine",
    "taux_succes_execution",
]