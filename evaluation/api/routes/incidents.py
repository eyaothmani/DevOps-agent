from fastapi import APIRouter, Depends

from evaluation.api.dependencies import MetricMode, metric_params
from evaluation.metrics import (
    compute_metrics,
    get_incidents,
    metriques_bugs_techniques,
    metriques_securite,
)
from evaluation.metrics import status_repartition as _status_repartition

router = APIRouter(prefix="/metrics")


@router.get("/status_repartition")
def status_repartition(
    params: tuple[MetricMode, str | None] = Depends(metric_params),
):
    """Return incident status distribution."""
    mode, alarm_type = params

    incidents = get_incidents(
        mode=mode,
        alarm_type=alarm_type,
    )

    return _status_repartition(incidents)


@router.get("/cas_echec")
def cas_echec(
    params: tuple[MetricMode, str | None] = Depends(metric_params),
):
    """Return documented evaluation failure cases."""
    mode, alarm_type = params

    data = compute_metrics(
        mode=mode,
        alarm_type=alarm_type,
    )

    return data["cas_echec_documentes"]


@router.get("/securite")
def securite(
    params: tuple[MetricMode, str | None] = Depends(metric_params),
):
    """Return security guardrail metrics."""
    mode, alarm_type = params

    incidents = get_incidents(
        mode=mode,
        alarm_type=alarm_type,
    )

    return metriques_securite(incidents)


@router.get("/bugs_techniques")
def bugs_techniques(
    params: tuple[MetricMode, str | None] = Depends(metric_params),
):
    """Return technical remediation failures."""
    mode, alarm_type = params

    incidents = get_incidents(
        mode=mode,
        alarm_type=alarm_type,
        exclude_dashboard_statuses=False,
    )

    return metriques_bugs_techniques(incidents)


@router.get("/incidents_bruts")
def incidents_bruts(
    params: tuple[MetricMode, str | None] = Depends(metric_params),
):
    """Return raw incidents."""
    mode, alarm_type = params

    return get_incidents(
        mode=mode,
        alarm_type=alarm_type,
    )