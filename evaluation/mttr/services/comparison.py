def compare_agent_and_infrastructure(
    infrastructure_seconds: float,
    agent_pipeline_seconds: float | None,
) -> dict:
    """Compare infrastructure resolution with agent pipeline latency."""

    return {
        "resolution_seconds_infra": infrastructure_seconds,
        "latence_pipeline_agent_seconds": agent_pipeline_seconds,
        "resolution_probablement_independante_agent": (
            agent_pipeline_seconds is not None
            and infrastructure_seconds < agent_pipeline_seconds
        ),
    }