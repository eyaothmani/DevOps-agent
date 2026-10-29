from unittest.mock import patch

from fastapi.testclient import TestClient

from evaluation.api.routes.performance import router


def create_client() -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@patch("evaluation.api.routes.performance.compute_metrics")
def test_mttr_par_type(mock_compute):
    mock_compute.return_value = {
        "mttr_secondes_par_type": {
            "cpu": 120.0,
            "memory": 240.0,
        }
    }

    response = create_client().get(
        "/metrics/mttr_par_type"
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "alarm_type": "cpu",
            "mttr_secondes": 120.0,
        },
        {
            "alarm_type": "memory",
            "mttr_secondes": 240.0,
        },
    ]


@patch("evaluation.api.routes.performance.compute_metrics")
def test_mttr_par_type_with_filters(mock_compute):
    mock_compute.return_value = {
        "mttr_secondes_par_type": {}
    }

    response = create_client().get(
        "/metrics/mttr_par_type"
        "?mode=live&alarm_type=cpu"
    )

    assert response.status_code == 200

    mock_compute.assert_called_once_with(
        mode="live",
        alarm_type="cpu",
    )


@patch("evaluation.api.routes.performance.compute_metrics")
def test_mttr_infra_reel(mock_compute):
    expected = {
        "disponible": True,
        "resolution_seconds": 120.0,
    }

    mock_compute.return_value = {
        "mttr_infra_reel": expected
    }

    response = create_client().get(
        "/metrics/mttr_infra_reel"
    )

    assert response.status_code == 200
    assert response.json() == expected


@patch("evaluation.api.routes.performance.compute_metrics")
def test_groundedness_par_type(mock_compute):
    mock_compute.return_value = {
        "groundedness_score_par_type": {
            "cpu": 0.90,
            "memory": 0.80,
        }
    }

    response = create_client().get(
        "/metrics/groundedness_par_type"
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "alarm_type": "cpu",
            "groundedness_score": 0.90,
        },
        {
            "alarm_type": "memory",
            "groundedness_score": 0.80,
        },
    ]