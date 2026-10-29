from unittest.mock import patch

from fastapi.testclient import TestClient

from evaluation.api.routes.incidents import router


def create_client() -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@patch("evaluation.api.routes.incidents.get_incidents")
@patch("evaluation.api.routes.incidents._status_repartition")
def test_status_repartition(
    mock_repartition,
    mock_get_incidents,
):
    incidents = [
        {
            "incident_id": "INC-001",
            "status": "EXECUTED",
        }
    ]

    mock_get_incidents.return_value = incidents
    mock_repartition.return_value = {
        "EXECUTED": 1,
    }

    response = create_client().get(
        "/metrics/status_repartition"
    )

    assert response.status_code == 200
    assert response.json() == {
        "EXECUTED": 1,
    }

    mock_get_incidents.assert_called_once_with(
        mode="auto",
        alarm_type=None,
    )

    mock_repartition.assert_called_once_with(
        incidents
    )


@patch("evaluation.api.routes.incidents.compute_metrics")
def test_cas_echec(mock_compute):
    expected = [
        {
            "incident_id": "INC-001",
            "reason": "timeout",
        }
    ]

    mock_compute.return_value = {
        "cas_echec_documentes": expected
    }

    response = create_client().get(
        "/metrics/cas_echec"
    )

    assert response.status_code == 200
    assert response.json() == expected


@patch("evaluation.api.routes.incidents.get_incidents")
@patch("evaluation.api.routes.incidents.metriques_securite")
def test_securite(
    mock_security,
    mock_get_incidents,
):
    incidents = [
        {
            "incident_id": "INC-001"
        }
    ]

    mock_get_incidents.return_value = incidents

    expected = {
        "nb_garde_fous_declenches": 2,
        "taux_garde_fous": 0.2,
    }

    mock_security.return_value = expected

    response = create_client().get(
        "/metrics/securite"
    )

    assert response.status_code == 200
    assert response.json() == expected

    mock_security.assert_called_once_with(
        incidents
    )


@patch("evaluation.api.routes.incidents.get_incidents")
@patch("evaluation.api.routes.incidents.metriques_bugs_techniques")
def test_bugs_techniques(
    mock_bugs,
    mock_get_incidents,
):
    incidents = [
        {
            "incident_id": "INC-001"
        }
    ]

    mock_get_incidents.return_value = incidents

    expected = {
        "nb_bugs_techniques": 1,
        "taux_bugs_techniques": 0.1,
    }

    mock_bugs.return_value = expected

    response = create_client().get(
        "/metrics/bugs_techniques"
    )

    assert response.status_code == 200
    assert response.json() == expected

    mock_get_incidents.assert_called_once_with(
        mode="auto",
        alarm_type=None,
        exclude_dashboard_statuses=False,
    )

    mock_bugs.assert_called_once_with(
        incidents
    )


@patch("evaluation.api.routes.incidents.get_incidents")
def test_incidents_bruts(mock_get_incidents):
    expected = [
        {
            "incident_id": "INC-001",
            "alarm_type": "cpu",
        }
    ]

    mock_get_incidents.return_value = expected

    response = create_client().get(
        "/metrics/incidents_bruts"
    )

    assert response.status_code == 200
    assert response.json() == expected


@patch("evaluation.api.routes.incidents.get_incidents")
def test_incidents_bruts_with_filters(mock_get_incidents):
    mock_get_incidents.return_value = []

    response = create_client().get(
        "/metrics/incidents_bruts"
        "?mode=live&alarm_type=memory"
    )

    assert response.status_code == 200

    mock_get_incidents.assert_called_once_with(
        mode="live",
        alarm_type="memory",
    )