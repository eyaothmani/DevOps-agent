from typing import Any


def build_kpis(metrics: dict[str, Any]) -> dict[str, Any]:
    """Build the KPI payload exposed to Grafana."""

    mttr_by_type = metrics["mttr_secondes_par_type"]

    mttr_moyen = (
        sum(mttr_by_type.values()) / len(mttr_by_type)
        if mttr_by_type
        else 0.0
    )

    mttr_infra = metrics.get("mttr_infra_reel")

    return {
        "nb_incidents": metrics["nb_incidents_analyses"],
        "groundedness_moyen": metrics["groundedness_score_moyen"],
        "taux_accord_juge": metrics["taux_accord_juge"],
        "taux_succes_execution": metrics["taux_succes_execution"],
        "taux_escalade_humaine": metrics["taux_escalade_humaine"],
        "mttr_moyen": mttr_moyen,
        "nb_cas_echec": metrics["nb_cas_echec"],
        "nb_bugs_techniques": (
            metrics["bugs_techniques"]["nb_bugs_techniques"]
        ),
        "taux_bugs_techniques": (
            metrics["bugs_techniques"]["taux_bugs_techniques"]
        ),
        "nb_garde_fous_declenches": (
            metrics["securite"]["nb_garde_fous_declenches"]
        ),
        "taux_garde_fous": (
            metrics["securite"]["taux_garde_fous"]
        ),
        "cout_total_usd": (
            metrics["cout_total_par_incident"]["cout_total_usd"]
        ),
        "cout_moyen_usd": (
            metrics["cout_total_par_incident"][
                "cout_moyen_par_incident_usd"
            ]
        ),
        "tokens_par_model": (
            metrics["repartition_tokens_par_model"]["tokens_par_model"]
        ),
        "nb_incidents_multi_modeles": (
            metrics["repartition_tokens_par_model"][
                "nb_incidents_multi_modeles"
            ]
        ),
        "mttr_infra_disponible": (
            mttr_infra.get("disponible", False)
            if isinstance(mttr_infra, dict)
            else False
        ),
    }


def build_mttr_by_type(
    metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build MTTR pipeline latency data grouped by alarm type."""

    return [
        {
            "alarm_type": alarm_type,
            "mttr_secondes": value,
        }
        for alarm_type, value
        in metrics["mttr_secondes_par_type"].items()
    ]


def build_groundedness_by_type(
    metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build groundedness scores grouped by alarm type."""

    return [
        {
            "alarm_type": alarm_type,
            "groundedness_score": value,
        }
        for alarm_type, value
        in metrics["groundedness_score_par_type"].items()
    ]


def build_tokens_by_model(
    metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build token usage grouped by model."""

    tokens = metrics["repartition_tokens_par_model"]

    return [
        {
            "model": model,
            "tokens": value,
        }
        for model, value in tokens["tokens_par_model"].items()
    ]