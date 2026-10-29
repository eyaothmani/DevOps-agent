from fastapi import APIRouter, Depends

from evaluation.api.dependencies import MetricMode, metric_params
from evaluation.metrics import compute_metrics

router = APIRouter(prefix="/metrics")


@router.get("/mttr_par_type")
def mttr_par_type(
    params: tuple[MetricMode, str | None] = Depends(metric_params),
):
    """Return agent pipeline latency by alarm type."""
    mode, alarm_type = params

    data = compute_metrics(
        mode=mode,
        alarm_type=alarm_type,
    )

    return [
        {
            "alarm_type": alarm_type,
            "mttr_secondes": value,
        }
        for alarm_type, value in data[
            "mttr_secondes_par_type"
        ].items()
    ]


@router.get("/mttr_infra_reel")
def mttr_infra_reel(
    params: tuple[MetricMode, str | None] = Depends(metric_params),
):
    """Return real infrastructure MTTR."""
    mode, alarm_type = params

    data = compute_metrics(
        mode=mode,
        alarm_type=alarm_type,
    )

    return data["mttr_infra_reel"]


@router.get("/groundedness_par_type")
def groundedness_par_type(
    params: tuple[MetricMode, str | None] = Depends(metric_params),
):
    """Return groundedness scores by alarm type."""
    mode, alarm_type = params

    data = compute_metrics(
        mode=mode,
        alarm_type=alarm_type,
    )

    return [
        {
            "alarm_type": alarm_type,
            "groundedness_score": value,
        }
        for alarm_type, value in data[
            "groundedness_score_par_type"
        ].items()
    ]