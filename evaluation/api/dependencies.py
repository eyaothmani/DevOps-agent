from typing import Literal

from fastapi import Query

MetricMode = Literal["auto", "offline", "live"]


def metric_params(
    mode: MetricMode = Query(
        default="auto",
        description="Evaluation mode",
    ),
    alarm_type: str | None = Query(
        default=None,
        description="Optional alarm type filter",
    ),
) -> tuple[MetricMode, str | None]:
    """Return common parameters used by metric endpoints."""
    return mode, alarm_type