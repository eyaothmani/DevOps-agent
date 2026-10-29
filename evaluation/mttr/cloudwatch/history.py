from datetime import datetime
from typing import Any


def get_alarm_history(
    alarm_name: str,
    start: datetime,
    end: datetime,
    client,
) -> list[dict[str, Any]]:
    """Retrieve CloudWatch state transitions for an alarm."""

    items: list[dict[str, Any]] = []

    params = {
        "AlarmName": alarm_name,
        "HistoryItemType": "StateUpdate",
        "StartDate": start,
        "EndDate": end,
        "ScanBy": "TimestampAscending",
        "MaxRecords": 100,
    }

    while True:
        response = client.describe_alarm_history(**params)

        items.extend(
            response.get("AlarmHistoryItems", [])
        )

        next_token = response.get("NextToken")

        if not next_token:
            break

        params["NextToken"] = next_token

    return items