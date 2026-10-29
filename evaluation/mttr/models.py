"""Domain models for the infrastructure MTTR evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class StateTransition:
    """A single CloudWatch alarm state change (e.g. OK -> ALARM)."""

    timestamp: datetime
    old_state: str | None
    new_state: str