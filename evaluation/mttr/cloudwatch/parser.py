import json
from typing import Any

from evaluation.mttr.models import StateTransition


def extract_state_transitions(
    history_items: list[dict[str, Any]],
) -> list[StateTransition]:
    """Extract state transitions from CloudWatch history items."""

    transitions: list[StateTransition] = []

    for item in history_items:
        raw_data = item.get("HistoryData")

        if not raw_data:
            continue

        try:
            data = (
                json.loads(raw_data)
                if isinstance(raw_data, str)
                else raw_data
            )
        except (ValueError, TypeError):
            continue

        new_state = data.get("newState", {}).get("stateValue")
        old_state = data.get("oldState", {}).get("stateValue")
        timestamp = item.get("Timestamp")

        if new_state is None or timestamp is None:
            continue

        transitions.append(
            StateTransition(
                timestamp=timestamp,
                old_state=old_state,
                new_state=new_state,
            )
        )

    return sorted(
        transitions,
        key=lambda transition: transition.timestamp,
    )