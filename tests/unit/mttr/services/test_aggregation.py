from unittest.mock import MagicMock, patch

from evaluation.mttr.services.aggregation import (
    calculate_mttr_by_alarm_type,
)


@patch(
    "evaluation.mttr.services.aggregation.create_cloudwatch_client"
)
@patch(
    "evaluation.mttr.services.aggregation.calculate_resolution"
)
def test_calculate_mttr_by_alarm_type(
    mock_calculate_resolution,
    mock_create_client,
):
    client = MagicMock()
    mock_create_client.return_value = client

    mock_calculate_resolution.side_effect = [
        {
            "resolution_seconds_infra": 100.0,
        },
        {
            "resolution_seconds_infra": 300.0,
        },
    ]

    items = [
        {
            "incident_id": "INC-001",
            "alarm_type": "cpu-high",
            "alert_received_at": "2026-08-09T10:00:00+00:00",
        },
        {
            "incident_id": "INC-002",
            "alarm_type": "cpu-high",
            "alert_received_at": "2026-08-09T11:00:00+00:00",
        },
    ]

    result = calculate_mttr_by_alarm_type(items)

    assert result["mttr_infra_secondes_par_type"] == {
        "cpu-high": 200.0,
    }

    assert result["nb_incidents_non_resolus_dans_fenetre"] == 0

    assert len(result["comparaison_agent_vs_infra"]) == 2


@patch(
    "evaluation.mttr.services.aggregation.create_cloudwatch_client"
)
@patch(
    "evaluation.mttr.services.aggregation.calculate_resolution"
)
def test_calculate_mttr_counts_unresolved_incidents(
    mock_calculate_resolution,
    mock_create_client,
):
    mock_create_client.return_value = MagicMock()

    mock_calculate_resolution.return_value = {
        "error": "not_resolved_in_window",
        "alarm_name": "cpu-high",
    }

    items = [
        {
            "incident_id": "INC-001",
            "alarm_type": "cpu-high",
            "alert_received_at": "2026-08-09T10:00:00+00:00",
        }
    ]

    result = calculate_mttr_by_alarm_type(items)

    assert result["nb_incidents_non_resolus_dans_fenetre"] == 1

    assert result["details_non_resolus"] == [
        {
            "incident_id": "INC-001",
            "alarm_type": "cpu-high",
            "raison": "not_resolved_in_window",
        }
    ]


@patch(
    "evaluation.mttr.services.aggregation.create_cloudwatch_client"
)
@patch(
    "evaluation.mttr.services.aggregation.calculate_resolution"
)
def test_calculate_mttr_skips_invalid_items(
    mock_calculate_resolution,
    mock_create_client,
):
    mock_create_client.return_value = MagicMock()

    items = [
        {},
        {
            "incident_id": "INC-002",
            "alarm_type": None,
            "alert_received_at": "2026-08-09T10:00:00+00:00",
        },
        {
            "incident_id": "INC-003",
            "alarm_type": "cpu-high",
            "alert_received_at": None,
        },
    ]

    result = calculate_mttr_by_alarm_type(items)

    assert result["mttr_infra_secondes_par_type"] == {}
    assert result["nb_incidents_non_resolus_dans_fenetre"] == 0

    mock_calculate_resolution.assert_not_called()


@patch(
    "evaluation.mttr.services.aggregation.create_cloudwatch_client"
)
@patch(
    "evaluation.mttr.services.aggregation.calculate_resolution"
)
def test_calculate_mttr_compares_agent_latency(
    mock_calculate_resolution,
    mock_create_client,
):
    mock_create_client.return_value = MagicMock()

    mock_calculate_resolution.return_value = {
        "resolution_seconds_infra": 100.0,
    }

    items = [
        {
            "incident_id": "INC-001",
            "alarm_type": "cpu-high",
            "alert_received_at": "2026-08-09T10:00:00+00:00",
        }
    ]

    result = calculate_mttr_by_alarm_type(
        items,
        pipeline_latency_by_incident={
            "INC-001": 300.0,
        },
    )

    comparison = result["comparaison_agent_vs_infra"][0]

    assert comparison["incident_id"] == "INC-001"
    assert comparison["resolution_seconds_infra"] == 100.0
    assert comparison["latence_pipeline_agent_seconds"] == 300.0
    assert (
        comparison[
            "resolution_probablement_independante_agent"
        ]
        is True
    )