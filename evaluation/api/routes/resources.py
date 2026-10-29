from typing import Annotated

from fastapi import APIRouter, Depends

from evaluation.api.dependencies import MetricMode, metric_params
from evaluation.metrics import compute_metrics

router = APIRouter(prefix="/metrics")


@router.get("/cout_par_incident")
def cout_par_incident(
    params: Annotated[tuple[MetricMode, str | None], Depends(metric_params)],
):
    """Return evaluation cost information."""
    mode, alarm_type = params
    data = compute_metrics(
        mode=mode,
        alarm_type=alarm_type,
    )
    return [data["cout_total_par_incident"]]


@router.get("/tokens_par_model")
def tokens_par_model(
    params: Annotated[tuple[MetricMode, str | None], Depends(metric_params)],
):
    """Return token usage grouped by model."""
    mode, alarm_type = params
    data = compute_metrics(
        mode=mode,
        alarm_type=alarm_type,
    )
    tokens = data["repartition_tokens_par_model"]
    return [
        {"model": model, "tokens": value}
        for model, value in tokens["tokens_par_model"].items()
    ]