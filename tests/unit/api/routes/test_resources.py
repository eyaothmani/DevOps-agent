from unittest.mock import patch

from fastapi.testclient import TestClient

from evaluation.api.routes.resources import router


def create_client() -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@patch("evaluation.api.routes.resources.compute_metrics")
def test_cout_par_incident(mock_compute):
    expected = {
        "cout_total_usd": 5.0,
        "cout_moyen_par_incident_usd": 0.5,
    }

    mock_compute.return_value = {
        "cout_total_par_incident": expected
    }

    response = create_client().get(
        "/metrics/cout_par_incident"
    )

    assert response.status_code == 200
    assert response.json() == [expected]


@patch("evaluation.api.routes.resources.compute_metrics")
def test_tokens_par_model(mock_compute):
    mock_compute.return_value = {
        "repartition_tokens_par_model": {
            "tokens_par_model": {
                "claude": 1000,
                "nova": 500,
            }
        }
    }

    response = create_client().get(
        "/metrics/tokens_par_model"
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "model": "claude",
            "tokens": 1000,
        },
        {
            "model": "nova",
            "tokens": 500,
        },
    ]


@patch("evaluation.api.routes.resources.compute_metrics")
def test_tokens_par_model_empty(mock_compute):
    mock_compute.return_value = {
        "repartition_tokens_par_model": {
            "tokens_par_model": {}
        }
    }

    response = create_client().get(
        "/metrics/tokens_par_model"
    )

    assert response.status_code == 200
    assert response.json() == []