from evaluation.api.metrics_kpi import (
    build_groundedness_by_type,
    build_kpis,
    build_mttr_by_type,
    build_tokens_by_model,
)


def make_metrics() -> dict:
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
        "groundedness_score_par_type": {
            "cpu": 0.90,
            "memory": 0.80,
        },
    }


def test_build_kpis():
    result = build_kpis(make_metrics())

    assert result == {
        "nb_incidents": 10,
        "groundedness_moyen": 0.85,
        "taux_accord_juge": 0.90,
        "taux_succes_execution": 0.80,
        "taux_escalade_humaine": 0.10,
        "mttr_moyen": 200.0,
        "nb_cas_echec": 2,
        "nb_bugs_techniques": 1,
        "taux_bugs_techniques": 0.10,
        "nb_garde_fous_declenches": 2,
        "taux_garde_fous": 0.20,
        "cout_total_usd": 5.0,
        "cout_moyen_usd": 0.5,
        "tokens_par_model": {
            "claude": 1000,
            "nova": 500,
        },
        "nb_incidents_multi_modeles": 3,
        "mttr_infra_disponible": True,
    }


def test_build_kpis_empty_mttr():
    metrics = make_metrics()
    metrics["mttr_secondes_par_type"] = {}

    result = build_kpis(metrics)

    assert result["mttr_moyen"] == 0.0


def test_build_kpis_mttr_infra_missing():
    metrics = make_metrics()
    metrics["mttr_infra_reel"] = None

    result = build_kpis(metrics)

    assert result["mttr_infra_disponible"] is False


def test_build_kpis_mttr_infra_not_dict():
    metrics = make_metrics()
    metrics["mttr_infra_reel"] = "unavailable"

    result = build_kpis(metrics)

    assert result["mttr_infra_disponible"] is False


def test_build_kpis_mttr_infra_disponible_false():
    metrics = make_metrics()
    metrics["mttr_infra_reel"] = {
        "disponible": False,
    }

    result = build_kpis(metrics)

    assert result["mttr_infra_disponible"] is False


def test_build_mttr_by_type():
    result = build_mttr_by_type(make_metrics())

    assert result == [
        {
            "alarm_type": "cpu",
            "mttr_secondes": 100.0,
        },
        {
            "alarm_type": "memory",
            "mttr_secondes": 300.0,
        },
    ]


def test_build_mttr_by_type_empty():
    metrics = make_metrics()
    metrics["mttr_secondes_par_type"] = {}

    assert build_mttr_by_type(metrics) == []


def test_build_groundedness_by_type():
    result = build_groundedness_by_type(make_metrics())

    assert result == [
        {
            "alarm_type": "cpu",
            "groundedness_score": 0.90,
        },
        {
            "alarm_type": "memory",
            "groundedness_score": 0.80,
        },
    ]


def test_build_groundedness_by_type_empty():
    metrics = make_metrics()
    metrics["groundedness_score_par_type"] = {}

    assert build_groundedness_by_type(metrics) == []


def test_build_tokens_by_model():
    result = build_tokens_by_model(make_metrics())

    assert result == [
        {
            "model": "claude",
            "tokens": 1000,
        },
        {
            "model": "nova",
            "tokens": 500,
        },
    ]


def test_build_tokens_by_model_empty():
    metrics = make_metrics()
    metrics["repartition_tokens_par_model"] = {
        "tokens_par_model": {},
    }

    assert build_tokens_by_model(metrics) == []