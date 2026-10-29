"""Internal data structures for metrics aggregation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class RowAccumulator:
    """Accumulates metrics while merging incident rows."""

    total_tokens: float = 0.0
    total_cost: float = 0.0
    calculated_cost: float = 0.0

    has_tokens: bool = False
    has_cost: bool = False
    has_calculated_cost: bool = False

    timestamps: list[float] = field(default_factory=list)

    nodes_seen: set[str] = field(default_factory=set)
    models_used: set[str] = field(default_factory=set)

    tokens_per_model: dict[str, float] = field(
        default_factory=lambda: defaultdict(float)
    )

    last_model: str | None = None