"""MTTR metrics computation."""

from __future__ import annotations

from typing import Any

from evaluation.metrics.converters import resolution_seconds
from evaluation.metrics.costs import (
    cout_total_par_incident,
    repartition_tokens_par_model,
)
from evaluation.metrics.filters import (
    exclude_dashboard_statuses,
    filter_by_alarm_type,
    filter_complete_incidents,
)
from evaluation.metrics.performance import (
    mttr_par_type,
    taux_escalade_humaine,
    taux_succes_execution,
)
from evaluation.metrics.quality import (
    groundedness_moyen,
    groundedness_par_type,
    taux_accord_juge,
    taux_calibration_confiance,
)
from evaluation.metrics.reliability import (
    cas_echec_documentes,
    status_repartition,
)
from evaluation.metrics.security import (
    metriques_bugs_techniques,
    metriques_securite,
)


def _resolution_seconds(
    item: dict[str, Any],
) -> float | None:
    """Compatibility wrapper around the shared resolution helper."""
    return resolution_seconds(item)


def _offline_mttr_result() -> dict[str, Any]:
    """Return the MTTR result when CloudWatch is unavailable."""
    return {
        "disponible": False,
        "raison": (
            "MTTR infrastructure offline : "
            "CloudWatch n'est pas disponible"
        ),
    }


def _load_real_mttr(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate real infrastructure MTTR."""
    try:
        pipeline_latency: dict[str, float] = {}

        for item in items:
            incident_id = item.get("incident_id")

            if not incident_id:
                continue

            resolution = _resolution_seconds(item)

            if resolution is not None:
                pipeline_latency[str(incident_id)] = resolution

        infra = mttr_infra_reel_par_type(
            items,
            pipeline_latency_par_incident=pipeline_latency,
        )

        infra["disponible"] = True

        return infra

    except ImportError as exc:
        return {
            "disponible": False,
            "raison": f"service MTTR indisponible: {exc}",
        }

    except (
        KeyError,
        TypeError,
        ValueError,
        OSError,
    ) as exc:
        return {
            "disponible": False,
            "raison": f"erreur MTTR: {exc}",
        }


def compute_metrics(
    mode: str = "offline",
    complete_only: bool = True,
    alarm_type: str | None = None,
) -> dict[str, Any]:
    """Compute the complete metrics report."""
    import evaluation.metrics as _pkg

    raw = _pkg.load_decisions(mode=mode)
    merged = _pkg.merge_items_by_incident(raw)

    if complete_only:
        merged = filter_complete_incidents(merged)

    bugs_techniques = metriques_bugs_techniques(merged)

    dashboard_items = exclude_dashboard_statuses(merged)

    if alarm_type is not None:
        dashboard_items = filter_by_alarm_type(dashboard_items, alarm_type)

    normalized_mode = mode.lower()

    if normalized_mode == "offline":
        source = "golden_dataset"
    elif normalized_mode == "live":
        source = "dynamodb"
    else:
        source = (
            "golden_dataset"
            if _pkg.GOLDEN_DATASET_PATH.exists()
            else "dynamodb"
        )

    mttr_infra = (
        _load_real_mttr(dashboard_items)
        if normalized_mode == "live"
        else _offline_mttr_result()
    )

    return {
        "source": source,
        "nb_incidents_analyses": len(dashboard_items),
        "nb_incidents_total_scannes": len(merged),
        "nb_incidents_exclus_bugs_techniques": bugs_techniques[
            "nb_bugs_techniques"
        ],
        "groundedness_score_moyen": groundedness_moyen(dashboard_items),
        "groundedness_score_par_type": groundedness_par_type(dashboard_items),
        "taux_accord_juge": taux_accord_juge(dashboard_items),
        "taux_calibration_confiance": taux_calibration_confiance(dashboard_items),
        "mttr_secondes_par_type": mttr_par_type(dashboard_items),
        "taux_succes_execution": taux_succes_execution(dashboard_items),
        "taux_escalade_humaine": taux_escalade_humaine(dashboard_items),
        "cout_total_par_incident": cout_total_par_incident(dashboard_items),
        "repartition_tokens_par_model": repartition_tokens_par_model(dashboard_items),
        "status_repartition": status_repartition(merged),
        "cas_echec_documentes": cas_echec_documentes(merged),
        "securite": metriques_securite(merged),
        "bugs_techniques": bugs_techniques,
        "mttr_infra_reel": mttr_infra,
    }


def get_incidents(
    mode: str = "offline",
    complete_only: bool = False,
    alarm_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return incidents optionally filtered by alarm type."""
    import evaluation.metrics as _pkg

    raw = _pkg.load_decisions(mode=mode)
    items = _pkg.merge_items_by_incident(raw)

    if complete_only:
        items = filter_complete_incidents(items)

    items = exclude_dashboard_statuses(items)

    if alarm_type is not None:
        items = filter_by_alarm_type(items, alarm_type)

    return items


def mttr_infra_reel_par_type(
    items: list[dict[str, Any]],
    pipeline_latency_par_incident: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Calculate infrastructure MTTR grouped by alarm type."""
    from evaluation.mttr.services.mttr_service import (
        mttr_infra_reel_par_type as real_mttr_infra_reel_par_type,
    )

    return real_mttr_infra_reel_par_type(
        items,
        pipeline_latency_par_incident=pipeline_latency_par_incident,
    )