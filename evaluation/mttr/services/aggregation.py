import statistics
from collections import defaultdict
from typing import Any

from evaluation.mttr.cloudwatch.client import create_cloudwatch_client
from evaluation.mttr.services.resolution import calculate_resolution


def calculate_mttr_by_alarm_type(
    items: list[dict[str, Any]],
    pipeline_latency_by_incident: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Aggregate infrastructure MTTR by alarm type."""

    client = create_cloudwatch_client()

    resolution_by_type: dict[str, list[float]] = defaultdict(list)
    unresolved: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []

    for item in items:
        alarm_type = item.get("alarm_type")
        alert_received_at = item.get("alert_received_at")

        if not alarm_type or not alert_received_at:
            continue

        result = calculate_resolution(
            alarm_type,
            alert_received_at,
            client,
        )

        if result is None or "error" in result:
            unresolved.append(
                {
                    "incident_id": item.get("incident_id"),
                    "alarm_type": alarm_type,
                    "raison": (result or {}).get(
                        "error",
                        "inconnu",
                    ),
                }
            )
            continue

        resolution_seconds = result["resolution_seconds_infra"]

        resolution_by_type[alarm_type].append(
            resolution_seconds
        )

        pipeline_seconds = None

        if pipeline_latency_by_incident:
            pipeline_seconds = pipeline_latency_by_incident.get(
                item.get("incident_id")
            )

        comparisons.append(
            {
                "incident_id": item.get("incident_id"),
                "alarm_type": alarm_type,
                "resolution_seconds_infra": resolution_seconds,
                "latence_pipeline_agent_seconds": pipeline_seconds,
                "resolution_probablement_independante_agent": (
                    pipeline_seconds is not None
                    and resolution_seconds < pipeline_seconds
                ),
            }
        )

    return {
        "mttr_infra_secondes_par_type": {
            alarm_type: round(
                statistics.mean(values),
                2,
            )
            for alarm_type, values in resolution_by_type.items()
        },
        "nb_incidents_non_resolus_dans_fenetre": len(unresolved),
        "details_non_resolus": unresolved,
        "comparaison_agent_vs_infra": comparisons,
    }