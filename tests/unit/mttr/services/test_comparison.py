from evaluation.mttr.services.comparison import (
    compare_agent_and_infrastructure,
)


def test_compare_agent_and_infrastructure_detects_independent_resolution():
    result = compare_agent_and_infrastructure(
        infrastructure_seconds=120.0,
        agent_pipeline_seconds=300.0,
    )

    assert result["resolution_seconds_infra"] == 120.0
    assert result["latence_pipeline_agent_seconds"] == 300.0
    assert (
        result["resolution_probablement_independante_agent"]
        is True
    )


def test_compare_agent_and_infrastructure_returns_false_when_agent_is_faster():
    result = compare_agent_and_infrastructure(
        infrastructure_seconds=300.0,
        agent_pipeline_seconds=120.0,
    )

    assert (
        result["resolution_probablement_independante_agent"]
        is False
    )


def test_compare_agent_and_infrastructure_handles_missing_pipeline_latency():
    result = compare_agent_and_infrastructure(
        infrastructure_seconds=120.0,
        agent_pipeline_seconds=None,
    )

    assert (
        result["latence_pipeline_agent_seconds"]
        is None
    )

    assert (
        result["resolution_probablement_independante_agent"]
        is False
    )