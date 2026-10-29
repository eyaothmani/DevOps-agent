
from __future__ import annotations

import json
import os
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import boto3

ALARM_NAME_TEMPLATE = os.getenv(
    "CLOUDWATCH_ALARM_NAME_TEMPLATE",
    "{alarm_type}",
)

SEARCH_WINDOW_MINUTES_BEFORE = int(
    os.getenv("MTTR_WINDOW_BEFORE_MIN", "2")
)

SEARCH_WINDOW_MINUTES_AFTER = int(
    os.getenv("MTTR_WINDOW_AFTER_MIN", "30")
)

AWS_REGION = os.getenv(
    "AWS_REGION",
    os.getenv("AWS_DEFAULT_REGION", "eu-north-1"),
)


def _cloudwatch_client():
    """Crée un client CloudWatch."""
    return boto3.client(
        "cloudwatch",
        region_name=AWS_REGION,
    )


def _get_alarm_history(
    alarm_name: str,
    start: datetime,
    end: datetime,
    client=None,
) -> list[dict[str, Any]]:
    """Récupère l'historique des changements d'état CloudWatch."""
    cw = client or _cloudwatch_client()

    items: list[dict[str, Any]] = []

    kwargs = {
        "AlarmName": alarm_name,
        "HistoryItemType": "StateUpdate",
        "StartDate": start,
        "EndDate": end,
        "ScanBy": "TimestampAscending",
        "MaxRecords": 100,
    }

    while True:
        response = cw.describe_alarm_history(**kwargs)

        items.extend(
            response.get("AlarmHistoryItems", [])
        )

        token = response.get("NextToken")

        if not token:
            break

        kwargs["NextToken"] = token

    return items


def _extract_state_transitions(
    history_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extrait les transitions ALARM/OK de l'historique CloudWatch."""
    transitions: list[dict[str, Any]] = []

    for item in history_items:
        raw = item.get("HistoryData")

        if not raw:
            continue

        try:
            data = (
                json.loads(raw)
                if isinstance(raw, str)
                else raw
            )
        except (ValueError, TypeError):
            continue

        new_state = (
            data.get("newState", {})
            .get("stateValue")
        )

        old_state = (
            data.get("oldState", {})
            .get("stateValue")
        )

        if new_state is None:
            continue

        timestamp = item.get("Timestamp")

        if timestamp is None:
            continue

        transitions.append(
            {
                "timestamp": timestamp,
                "old_state": old_state,
                "new_state": new_state,
            }
        )

    return sorted(
        transitions,
        key=lambda transition: transition["timestamp"],
    )


def resolution_seconds_reel(
    alarm_type: str,
    alert_received_at: str,
    client=None,
) -> dict[str, Any] | None:
    """
    Calcule le temps réel de résolution infrastructure.

    Mesure :
        CloudWatch ALARM -> CloudWatch OK

    Cette métrique est indépendante du temps de traitement
    du pipeline de l'agent.
    """
    try:
        start_dt = datetime.fromisoformat(
            alert_received_at
        )
    except (ValueError, AttributeError):
        return None

    alarm_name = ALARM_NAME_TEMPLATE.format(
        alarm_type=alarm_type
    )

    window_start = (
        start_dt
        - timedelta(minutes=SEARCH_WINDOW_MINUTES_BEFORE)
    )

    window_end = (
        start_dt
        + timedelta(minutes=SEARCH_WINDOW_MINUTES_AFTER)
    )

    try:
        history = _get_alarm_history(
            alarm_name=alarm_name,
            start=window_start,
            end=window_end,
            client=client,
        )

    except Exception as exc:  # noqa: BLE001
        return {
            "error": f"cloudwatch_unavailable: {exc}",
            "alarm_name": alarm_name,
        }

    transitions = _extract_state_transitions(history)

    if not transitions:
        return {
            "error": "no_history_found",
            "alarm_name": alarm_name,
        }

    alarm_transition = next(
        (
            transition
            for transition in transitions
            if (
                transition["new_state"] == "ALARM"
                and transition["timestamp"] >= window_start
            )
        ),
        None,
    )

    if alarm_transition is None:
        return {
            "error": "no_alarm_transition_found",
            "alarm_name": alarm_name,
        }

    ok_transition = next(
        (
            transition
            for transition in transitions
            if (
                transition["new_state"] == "OK"
                and transition["timestamp"]
                > alarm_transition["timestamp"]
            )
        ),
        None,
    )

    if ok_transition is None:
        return {
            "error": "not_resolved_in_window",
            "alarm_name": alarm_name,
            "alarm_at": alarm_transition[
                "timestamp"
            ].isoformat(),
        }

    delta_seconds = (
        ok_transition["timestamp"]
        - alarm_transition["timestamp"]
    ).total_seconds()

    return {
        "alarm_name": alarm_name,
        "alarm_at": alarm_transition[
            "timestamp"
        ].isoformat(),
        "ok_at": ok_transition[
            "timestamp"
        ].isoformat(),
        "resolution_seconds_infra": round(
            delta_seconds,
            2,
        ),
    }


def mttr_infra_reel_par_type(
    items: list[dict[str, Any]],
    pipeline_latency_par_incident: dict[str, float]
    | None = None,
) -> dict[str, Any]:
    """
    Calcule le MTTR infrastructure réel par type d'alarme.

    Compare également :
        - MTTR infrastructure CloudWatch
        - latence du pipeline agent
    """
    cw = _cloudwatch_client()

    par_type: dict[str, list[float]] = defaultdict(list)

    non_resolus: list[dict[str, Any]] = []

    comparaisons: list[dict[str, Any]] = []

    for item in items:
        alarm_type = item.get("alarm_type")
        alert_at = item.get("alert_received_at")

        if not alarm_type or not alert_at:
            continue

        result = resolution_seconds_reel(
            alarm_type=alarm_type,
            alert_received_at=alert_at,
            client=cw,
        )

        if result is None or "error" in result:
            non_resolus.append(
                {
                    "incident_id": item.get("incident_id"),
                    "alarm_type": alarm_type,
                    "raison": (
                        result or {}
                    ).get(
                        "error",
                        "inconnu",
                    ),
                }
            )
            continue

        infra_seconds = result[
            "resolution_seconds_infra"
        ]

        par_type[str(alarm_type)].append(
            infra_seconds
        )

        pipeline_seconds = None

        if pipeline_latency_par_incident:
            pipeline_seconds = (
                pipeline_latency_par_incident.get(
                    item.get("incident_id")
                )
            )

        comparaisons.append(
            {
                "incident_id": item.get(
                    "incident_id"
                ),
                "alarm_type": alarm_type,
                "resolution_seconds_infra": (
                    infra_seconds
                ),
                "latence_pipeline_agent_seconds": (
                    pipeline_seconds
                ),
                "resolution_probablement_independante_agent": (
                    pipeline_seconds is not None
                    and infra_seconds < pipeline_seconds
                ),
            }
        )

    return {
        "mttr_infra_secondes_par_type": {
            alarm_type: round(
                statistics.mean(values),
                2,
            )
            for alarm_type, values in par_type.items()
        },
        "nb_incidents_non_resolus_dans_fenetre": (
            len(non_resolus)
        ),
        "details_non_resolus": non_resolus,
        "comparaison_agent_vs_infra": comparaisons,
    }

