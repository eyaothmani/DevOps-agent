from datetime import UTC, datetime
from unittest.mock import MagicMock

from evaluation.mttr.cloudwatch.history import get_alarm_history


def test_get_alarm_history_returns_items():
    client = MagicMock()

    client.describe_alarm_history.return_value = {
        "AlarmHistoryItems": [
            {"HistoryData": "item-1"},
            {"HistoryData": "item-2"},
        ]
    }

    start = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
    end = datetime(2026, 8, 9, 10, 30, tzinfo=UTC)

    result = get_alarm_history(
        "eya-asg-cpu-high",
        start,
        end,
        client,
    )

    assert len(result) == 2
    assert result[0]["HistoryData"] == "item-1"

    client.describe_alarm_history.assert_called_once()


def test_get_alarm_history_handles_pagination():
    client = MagicMock()

    client.describe_alarm_history.side_effect = [
        {
            "AlarmHistoryItems": [
                {"HistoryData": "item-1"},
            ],
            "NextToken": "token-123",
        },
        {
            "AlarmHistoryItems": [
                {"HistoryData": "item-2"},
            ]
        },
    ]

    start = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
    end = datetime(2026, 8, 9, 10, 30, tzinfo=UTC)

    result = get_alarm_history(
        "eya-asg-cpu-high",
        start,
        end,
        client,
    )

    assert len(result) == 2
    assert result[0]["HistoryData"] == "item-1"
    assert result[1]["HistoryData"] == "item-2"

    assert client.describe_alarm_history.call_count == 2

    second_call = client.describe_alarm_history.call_args_list[1]

    assert second_call.kwargs["NextToken"] == "token-123"


def test_get_alarm_history_returns_empty_list_when_no_history():
    client = MagicMock()

    client.describe_alarm_history.return_value = {
        "AlarmHistoryItems": []
    }

    start = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
    end = datetime(2026, 8, 9, 10, 30, tzinfo=UTC)

    result = get_alarm_history(
        "eya-asg-cpu-high",
        start,
        end,
        client,
    )

    assert result == []