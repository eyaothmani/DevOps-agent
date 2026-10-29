from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from evaluation.mttr.services.resolution import calculate_resolution


def _history_item(timestamp, old_state, new_state):
    return {
        "Timestamp": timestamp,
        "HistoryData": (
            f'{{"oldState":{{"stateValue":"{old_state}"}},'
            f'"newState":{{"stateValue":"{new_state}"}}}}'
        ),
    }


@patch(
    "evaluation.mttr.services.resolution.get_alarm_history"
)
def test_calculate_resolution_returns_alarm_to_ok_duration(
    mock_get_history,
):
    alarm_at = datetime(
        2026,
        8,
        9,
        10,
        0,
        tzinfo=UTC,
    )

    ok_at = datetime(
        2026,
        8,
        9,
        10,
        5,
        tzinfo=UTC,
    )

    mock_get_history.return_value = [
        _history_item(alarm_at, "OK", "ALARM"),
        _history_item(ok_at, "ALARM", "OK"),
    ]

    client = MagicMock()

    result = calculate_resolution(
        "cpu-high",
        "2026-08-09T10:00:00+00:00",
        client,
    )

    assert result["alarm_name"] == "cpu-high"
    assert result["resolution_seconds_infra"] == 300.0
    assert result["alarm_at"] == alarm_at.isoformat()
    assert result["ok_at"] == ok_at.isoformat()


@patch(
    "evaluation.mttr.services.resolution.get_alarm_history"
)
def test_calculate_resolution_returns_none_for_invalid_date(
    mock_get_history,
):
    result = calculate_resolution(
        "cpu-high",
        "invalid-date",
        MagicMock(),
    )

    assert result is None
    mock_get_history.assert_not_called()


@patch(
    "evaluation.mttr.services.resolution.get_alarm_history"
)
def test_calculate_resolution_returns_no_history_error(
    mock_get_history,
):
    mock_get_history.return_value = []

    result = calculate_resolution(
        "cpu-high",
        "2026-08-09T10:00:00+00:00",
        MagicMock(),
    )

    assert result == {
        "error": "no_history_found",
        "alarm_name": "cpu-high",
    }


@patch(
    "evaluation.mttr.services.resolution.get_alarm_history"
)
def test_calculate_resolution_returns_missing_alarm_error(
    mock_get_history,
):
    mock_get_history.return_value = [
        _history_item(
            datetime(
                2026,
                8,
                9,
                10,
                5,
                tzinfo=UTC,
            ),
            "OK",
            "OK",
        )
    ]

    result = calculate_resolution(
        "cpu-high",
        "2026-08-09T10:00:00+00:00",
        MagicMock(),
    )

    assert result["error"] == "no_alarm_transition_found"


@patch(
    "evaluation.mttr.services.resolution.get_alarm_history"
)
def test_calculate_resolution_returns_not_resolved_error(
    mock_get_history,
):
    alarm_at = datetime(
        2026,
        8,
        9,
        10,
        0,
        tzinfo=UTC,
    )

    mock_get_history.return_value = [
        _history_item(alarm_at, "OK", "ALARM"),
    ]

    result = calculate_resolution(
        "cpu-high",
        "2026-08-09T10:00:00+00:00",
        MagicMock(),
    )

    assert result["error"] == "not_resolved_in_window"
    assert result["alarm_at"] == alarm_at.isoformat()


@patch(
    "evaluation.mttr.services.resolution.get_alarm_history"
)
def test_calculate_resolution_handles_cloudwatch_failure(
    mock_get_history,
):
    mock_get_history.side_effect = RuntimeError(
        "AWS unavailable"
    )

    result = calculate_resolution(
        "cpu-high",
        "2026-08-09T10:00:00+00:00",
        MagicMock(),
    )

    assert result["error"] == (
        "cloudwatch_unavailable: AWS unavailable"
    )
    assert result["alarm_name"] == "cpu-high"