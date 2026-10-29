from unittest.mock import patch

from fastapi.testclient import TestClient

from evaluation.api.routes.overview import router


def create_client() -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def base_metrics() -> dict:
    return {
        "nb_incidents_analyses": 10,
        "groundedness_score_moyen": 0.85,
        "taux_accord_juge": 0.90,
        "taux_succes_execution": 0.80,
        "taux_escalade_humaine": 0.10,
        "mttr_secondes_par_type": {
            "cpu": 100.0,
            "memory": 300.0,
        },
        "nb_cas_echec": 2,
        "bugs_techniques": {
            "nb_bugs_techniques": 1,
            "taux_bugs_techniques": 0.10,
        },
        "securite": {
            "nb_garde_fous_declenches": 2,
            "taux_garde_fous": 0.20,
        },
        "cout_total_par_incident": {
            "cout_total_usd": 5.0,
            "cout_moyen_par_incident_usd": 0.5,
        },
        "repartition_tokens_par_model": {
            "tokens_par_model": {
                "claude": 1000,
                "nova": 500,
            },
            "nb_incidents_multi_modeles": 3,
        },
        "mttr_infra_reel": {
            "disponible": True,
        },
    }


@patch("evaluation.api.routes.overview.compute_metrics")
def test_metrics(mock_compute):
    expected = {"nb_incidents_analyses": 10}
    mock_compute.return_value = expected

    response = create_client().get("/metrics")

    assert response.status_code == 200
    assert response.json() == expected

    mock_compute.assert_called_once_with(
        mode="auto",
        alarm_type=None,
    )


@patch("evaluation.api.routes.overview.compute_metrics")
def test_metrics_with_parameters(mock_compute):
    mock_compute.return_value = {}

    response = create_client().get(
        "/metrics?mode=offline&alarm_type=cpu-high"
    )

    assert response.status_code == 200

    mock_compute.assert_called_once_with(
        mode="offline",
        alarm_type="cpu-high",
    )


def test_metrics_invalid_mode():
    response = create_client().get(
        "/metrics?mode=invalid"
    )

    assert response.status_code == 422


@patch("evaluation.api.routes.overview.compute_metrics")
def test_kpis(mock_compute):
    mock_compute.return_value = base_metrics()

    response = create_client().get("/metrics/kpis")

    assert response.status_code == 200

    data = response.json()

    assert data["nb_incidents"] == 10
    assert data["groundedness_moyen"] == 0.85
    assert data["taux_accord_juge"] == 0.90
    assert data["taux_succes_execution"] == 0.80
    assert data["taux_escalade_humaine"] == 0.10
    assert data["mttr_moyen"] == 200.0
    assert data["nb_cas_echec"] == 2
    assert data["nb_bugs_techniques"] == 1
    assert data["taux_bugs_techniques"] == 0.10
    assert data["nb_garde_fous_declenches"] == 2
    assert data["taux_garde_fous"] == 0.20
    assert data["cout_total_usd"] == 5.0
    assert data["cout_moyen_usd"] == 0.5
    assert data["tokens_par_model"] == {
        "claude": 1000,
        "nova": 500,
    }
    assert data["nb_incidents_multi_modeles"] == 3
    assert data["mttr_infra_disponible"] is True


@patch("evaluation.api.routes.overview.compute_metrics")
def test_kpis_empty_mttr(mock_compute):
    data = base_metrics()
    data["mttr_secondes_par_type"] = {}

    mock_compute.return_value = data

    response = create_client().get("/metrics/kpis")

    assert response.status_code == 200
    assert response.json()["mttr_moyen"] == 0.0


@patch("evaluation.api.routes.overview.compute_metrics")
def test_kpis_mttr_infra_unavailable(mock_compute):
    data = base_metrics()
    data["mttr_infra_reel"] = None

    mock_compute.return_value = data

    response = create_client().get("/metrics/kpis")

    assert response.status_code == 200
    assert response.json()["mttr_infra_disponible"] is False


@patch("evaluation.api.routes.overview.compute_metrics")
def test_kpis_mttr_infra_not_dict(mock_compute):
    data = base_metrics()
    data["mttr_infra_reel"] = "unavailable"

    mock_compute.return_value = data

    response = create_client().get("/metrics/kpis")

    assert response.status_code == 200
    assert response.json()["mttr_infra_disponible"] is False