from unittest.mock import patch

from evaluation.metrics.mttr import (
    _load_real_mttr,
    _offline_mttr_result,
    _resolution_seconds,
    compute_metrics,
    get_incidents,
)


def test_resolution_seconds_with_valid_timestamps():
    item = {
        "nb_node_writes": 3,
        "alert_received_at": "2026-08-09T10:00:00+00:00",
        "resolved_at": "2026-08-09T10:00:30+00:00",
    }

    assert _resolution_seconds(item) == 30.0


def test_resolution_seconds_returns_none_when_invalid():
    item = {
        "nb_node_writes": 3,
        "alert_received_at": "invalid",
        "resolved_at": "also-invalid",
    }

    assert _resolution_seconds(item) is None


def test_resolution_seconds_returns_none_for_negative_duration():
    item = {
        "nb_node_writes": 3,
        "alert_received_at": "2026-08-09T10:01:00+00:00",
        "resolved_at": "2026-08-09T10:00:00+00:00",
    }

    assert _resolution_seconds(item) is None


def test_resolution_seconds_requires_two_node_writes():
    item = {
        "nb_node_writes": 1,
        "alert_received_at": "2026-08-09T10:00:00+00:00",
        "resolved_at": "2026-08-09T10:00:30+00:00",
    }

    assert _resolution_seconds(item) is None


def test_offline_mttr_result():
    result = _offline_mttr_result()

    assert result["disponible"] is False
    assert "offline" in result["raison"]
    assert "CloudWatch" in result["raison"]


def test_load_real_mttr_success():
    items = [
        {
            "incident_id": "inc-001",
            "alarm_type": "cpu_high",
            "alert_received_at": "2026-08-09T10:00:00+00:00",
            "resolved_at": "2026-08-09T10:00:20+00:00",
        }
    ]

    expected = {
        "mttr_infra_secondes_par_type": {
            "cpu_high": 15.0,
        }
    }

    with patch(
        "evaluation.mttr.services.mttr_service.mttr_infra_reel_par_type",
        return_value=expected.copy(),
    ):
        result = _load_real_mttr(items)

    assert result["disponible"] is True
    assert result["mttr_infra_secondes_par_type"] == {
        "cpu_high": 15.0
    }


def test_load_real_mttr_import_error():
    items = []

    with patch(
        "evaluation.metrics.mttr.mttr_infra_reel_par_type",
        side_effect=ImportError("service missing"),
    ):
        result = _load_real_mttr(items)

    assert result["disponible"] is False
    assert "service MTTR indisponible" in result["raison"]


def test_load_real_mttr_runtime_error():
    items = []

    with patch(
        "evaluation.metrics.mttr.mttr_infra_reel_par_type",
        side_effect=ValueError("invalid data"),
    ):
        result = _load_real_mttr(items)

    assert result["disponible"] is False
    assert "erreur MTTR" in result["raison"]


def test_compute_metrics_offline():
    result = compute_metrics(
        mode="offline",
        complete_only=False,
    )

    assert isinstance(result, dict)
    assert "source" in result
    assert "nb_incidents_analyses" in result
    assert "mttr_infra_reel" in result

    assert result["mttr_infra_reel"]["disponible"] is False


def test_compute_metrics_contains_expected_sections():
    result = compute_metrics(
        mode="offline",
        complete_only=False,
    )

    expected_keys = {
        "source",
        "nb_incidents_analyses",
        "nb_incidents_total_scannes",
        "groundedness_score_moyen",
        "groundedness_score_par_type",
        "taux_accord_juge",
        "taux_calibration_confiance",
        "mttr_secondes_par_type",
        "taux_succes_execution",
        "taux_escalade_humaine",
        "cout_total_par_incident",
        "repartition_tokens_par_model",
        "status_repartition",
        "cas_echec_documentes",
        "securite",
        "bugs_techniques",
        "mttr_infra_reel",
    }

    assert expected_keys.issubset(result.keys())


def test_get_incidents_returns_list():
    result = get_incidents(
        mode="offline",
        complete_only=False,
    )

    assert isinstance(result, list)


def test_get_incidents_filter_alarm_type():
    result = get_incidents(
        mode="offline",
        complete_only=False,
        alarm_type="cpu_high",
    )

    assert isinstance(result, list)

    assert all(
        item.get("alarm_type") == "cpu_high"
        for item in result
    )