from typing import Annotated

from fastapi import APIRouter, Depends

from evaluation.api.dependencies import MetricMode, metric_params
from evaluation.metrics import compute_metrics

router = APIRouter(prefix="/metrics")


@router.get("")
def metrics(
    params: Annotated[tuple[MetricMode, str | None], Depends(metric_params)],
):
    """Return complete evaluation metrics."""
    mode, alarm_type = params
    return compute_metrics(
        mode=mode,
        alarm_type=alarm_type,
    )


@router.get("/kpis")
def kpis(
    params: Annotated[tuple[MetricMode, str | None], Depends(metric_params)],
):
    """Return the main KPIs used by Grafana."""
    mode, alarm_type = params
    data = compute_metrics(
        mode=mode,
        alarm_type=alarm_type,
    )
    mttr_values = data["mttr_secondes_par_type"]
    mttr_moyen = _average(mttr_values.values())
    mttr_infra = data.get("mttr_infra_reel")
    return {
        "nb_incidents": data["nb_incidents_analyses"],
        "groundedness_moyen": data["groundedness_score_moyen"],
        "taux_accord_juge": data["taux_accord_juge"],
        "taux_succes_execution": data["taux_succes_execution"],
        "taux_escalade_humaine": data["taux_escalade_humaine"],
        "mttr_moyen": mttr_moyen,
        "nb_cas_echec": data["nb_cas_echec"],
        "nb_bugs_techniques": (
            data["bugs_techniques"]["nb_bugs_techniques"]
        ),
        "taux_bugs_techniques": (
            data["bugs_techniques"]["taux_bugs_techniques"]
        ),
        "nb_garde_fous_declenches": (
            data["securite"]["nb_garde_fous_declenches"]
        ),
        "taux_garde_fous": (
            data["securite"]["taux_garde_fous"]
        ),
        "cout_total_usd": (
            data["cout_total_par_incident"]["cout_total_usd"]
        ),
        "cout_moyen_usd": (
            data["cout_total_par_incident"][
                "cout_moyen_par_incident_usd"
            ]
        ),
        "tokens_par_model": (
            data["repartition_tokens_par_model"]["tokens_par_model"]
        ),
        "nb_incidents_multi_modeles": (
            data["repartition_tokens_par_model"][
                "nb_incidents_multi_modeles"
            ]
        ),
        "mttr_infra_disponible": _infra_available(mttr_infra),
    }


def _average(values) -> float:
    """Return the average of values."""
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


def _infra_available(value) -> bool:
    """Return whether real infrastructure MTTR is available."""
    return (
        isinstance(value, dict)
        and value.get("disponible", False)
    )