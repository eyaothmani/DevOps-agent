from datetime import UTC, datetime

from evaluation.mttr.cloudwatch.parser import extract_state_transitions


def test_extract_state_transitions_from_valid_history():
    timestamp = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)

    history = [
        {
            "Timestamp": timestamp,
            "HistoryData": (
                '{"oldState":{"stateValue":"OK"},'
                '"newState":{"stateValue":"ALARM"}}'
            ),
        }
    ]

    result = extract_state_transitions(history)

    assert len(result) == 1
    assert result[0].timestamp == timestamp
    assert result[0].old_state == "OK"
    assert result[0].new_state == "ALARM"


def test_extract_state_transitions_supports_dict_history_data():
    timestamp = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)

    history = [
        {
            "Timestamp": timestamp,
            "HistoryData": {
                "oldState": {"stateValue": "ALARM"},
                "newState": {"stateValue": "OK"},
            },
        }
    ]

    result = extract_state_transitions(history)

    assert len(result) == 1
    assert result[0].old_state == "ALARM"
    assert result[0].new_state == "OK"


def test_extract_state_transitions_ignores_invalid_json():
    history = [
        {
            "Timestamp": datetime.now(UTC),
            "HistoryData": "{invalid-json",
        }
    ]

    result = extract_state_transitions(history)

    assert result == []


def test_extract_state_transitions_ignores_missing_history_data():
    history = [
        {
            "Timestamp": datetime.now(UTC),
        }
    ]

    result = extract_state_transitions(history)

    assert result == []


def test_extract_state_transitions_ignores_missing_new_state():
    history = [
        {
            "Timestamp": datetime.now(UTC),
            "HistoryData": (
                '{"oldState":{"stateValue":"OK"}}'
            ),
        }
    ]

    result = extract_state_transitions(history)

    assert result == []


def test_extract_state_transitions_is_sorted_by_timestamp():
    first = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
    second = datetime(2026, 8, 9, 10, 5, tzinfo=UTC)

    history = [
        {
            "Timestamp": second,
            "HistoryData": (
                '{"oldState":{"stateValue":"ALARM"},'
                '"newState":{"stateValue":"OK"}}'
            ),
        },
        {
            "Timestamp": first,
            "HistoryData": (
                '{"oldState":{"stateValue":"OK"},'
                '"newState":{"stateValue":"ALARM"}}'
            ),
        },
    ]

    result = extract_state_transitions(history)

    assert result[0].timestamp == first
    assert result[0].new_state == "ALARM"

    assert result[1].timestamp == second
    assert result[1].new_state == "OK"