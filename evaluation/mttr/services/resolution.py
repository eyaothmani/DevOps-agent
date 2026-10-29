from datetime import datetime, timedelta
from typing import Any

from evaluation.mttr.cloudwatch.history import get_alarm_history
from evaluation.mttr.cloudwatch.parser import extract_state_transitions
from evaluation.mttr.config import (
    ALARM_NAME_TEMPLATE,
    SEARCH_WINDOW_MINUTES_AFTER,
    SEARCH_WINDOW_MINUTES_BEFORE,
)


def calculate_resolution(
    alarm_type: str,
    alert_received_at: str,
    client,
) -> dict[str, Any] | None:
    """Calculate real infrastructure resolution time."""

    try:
        start_dt = datetime.fromisoformat(
            alert_received_at
        )
    except (ValueError, AttributeError):
        return None

    alarm_name = ALARM_NAME_TEMPLATE.format(
        alarm_type=alarm_type,
    )

    window_start = start_dt - timedelta(
        minutes=SEARCH_WINDOW_MINUTES_BEFORE,
    )

    window_end = start_dt + timedelta(
        minutes=SEARCH_WINDOW_MINUTES_AFTER,
    )

    try:
        history = get_alarm_history(
            alarm_name,
            window_start,
            window_end,
            client,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "error": f"cloudwatch_unavailable: {exc}",
            "alarm_name": alarm_name,
        }

    transitions = extract_state_transitions(history)

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
                transition.new_state == "ALARM"
                and transition.timestamp >= window_start
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
                transition.new_state == "OK"
                and transition.timestamp > alarm_transition.timestamp
            )
        ),
        None,
    )

    if ok_transition is None:
        return {
            "error": "not_resolved_in_window",
            "alarm_name": alarm_name,
            "alarm_at": alarm_transition.timestamp.isoformat(),
        }

    resolution_seconds = (
        ok_transition.timestamp - alarm_transition.timestamp
    ).total_seconds()

    return {
        "alarm_name": alarm_name,
        "alarm_at": alarm_transition.timestamp.isoformat(),
        "ok_at": ok_transition.timestamp.isoformat(),
        "resolution_seconds_infra": round(
            resolution_seconds,
            2,
        ),
    }