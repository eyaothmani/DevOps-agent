"""Data loaders for the metrics engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import DYNAMO_TABLE_NAME, GOLDEN_DATASET_PATH


def load_from_dynamodb() -> list[dict[str, Any]]:
    """Load all decision records from DynamoDB."""
    import boto3

    table = boto3.resource("dynamodb").Table(DYNAMO_TABLE_NAME)

    items: list[dict[str, Any]] = []
    scan_kwargs: dict[str, Any] = {}

    while True:
        response = table.scan(**scan_kwargs)

        page_items = response.get("Items", [])
        items.extend(page_items)

        last_key = response.get("LastEvaluatedKey")

        if not last_key:
            break

        scan_kwargs["ExclusiveStartKey"] = last_key

    return items


def load_from_golden_dataset(
    path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Load incident records from the golden dataset."""
    dataset_path = Path(path) if path is not None else GOLDEN_DATASET_PATH

    with dataset_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise TypeError("Golden dataset must contain a JSON list.")

    return data
def load_decisions(
    mode: str = "offline",
) -> list[dict[str, Any]]:
    """Load decisions according to the requested mode."""
    normalized_mode = mode.lower()

    if normalized_mode == "offline":
        return load_from_golden_dataset()

    if normalized_mode == "live":
        return load_from_dynamodb()

    if normalized_mode == "auto":
        if GOLDEN_DATASET_PATH.exists():
            return load_from_golden_dataset()

        return load_from_dynamodb()

    raise ValueError(f"Unsupported metrics mode: {mode}")