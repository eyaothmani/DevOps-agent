"""Configuration for the metrics engine."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DYNAMO_TABLE_NAME = os.getenv(
    "AGENT_DECISIONS_TABLE",
    "agent_decisions",
)

GOLDEN_DATASET_PATH = Path(
    os.getenv(
        "GOLDEN_DATASET_PATH",
        str(BASE_DIR / "golden_dataset.json"),
    )
)

REQUIRE_JUDGE_FOR_COMPLETE = False

PRICE_PER_TOKEN: dict[str, float] = {
    "haiku": 0.00000075,
    "sonnet": 0.000009,
    "default": 0.000005,
}