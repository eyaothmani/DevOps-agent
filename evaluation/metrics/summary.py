"""Metrics summary builder."""

from __future__ import annotations

from typing import Any

from .costs import (
    cout_total_par_incident,
    repartition_tokens_par_model,
)
from .performance import (
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
from .security import (
    metriques_bugs_techniques,
    metriques_securite,
)


def build_metrics_summary(
    *,
    items: list[dict[str, Any]],
    all_merged: list[dict[str, Any]],
    items_before_exclusion: list[
        dict[str, Any]
    ],
    complete_only: bool,
    source: str,
) -> dict[str, Any]:
    """Build the complete metrics response."""
    failure_cases = (
        cas_echec_documentes(items)
    )

    excluded_technical = (
        len(items_before_exclusion)
        - len(items)
    )

    excluded_incomplete = (
        len(all_merged)
        - len(items_before_exclusion)
        if complete_only
        else 0
    )

    return {
        "source": source,
        "nb_incidents_analyses": len(
            items
        ),
        "nb_incidents_total_scannes": len(
            all_merged
        ),
        "nb_incidents_exclus_incomplets": (
            excluded_incomplete
        ),
        "nb_incidents_exclus_bugs_techniques": (
            excluded_technical
        ),
        "groundedness_score_moyen": (
            groundedness_moyen(items)
        ),
        "groundedness_score_par_type": (
            groundedness_par_type(items)
        ),
        "taux_accord_juge": (
            taux_accord_juge(items)
        ),
        "taux_calibration_confiance": (
            taux_calibration_confiance(items)
        ),
        "mttr_secondes_par_type": (
            mttr_par_type(items)
        ),
        "taux_succes_execution": (
            taux_succes_execution(items)
        ),
        "taux_escalade_humaine": (
            taux_escalade_humaine(items)
        ),
        "cout_total_par_incident": (
            cout_total_par_incident(items)
        ),
        "repartition_tokens_par_model": (
            repartition_tokens_par_model(items)
        ),
        "status_repartition": (
            status_repartition(items)
        ),
        "cas_echec_documentes": (
            failure_cases
        ),
        "nb_cas_echec": len(
            failure_cases
        ),
        "securite": (
            metriques_securite(items)
        ),
        "bugs_techniques": (
            metriques_bugs_techniques(
                items_before_exclusion
            )
        ),
    }