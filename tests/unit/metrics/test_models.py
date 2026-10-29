"""Unit tests for evaluation.metrics.models."""

from __future__ import annotations

from evaluation.metrics.models import RowAccumulator


def test_default_values():
    acc = RowAccumulator()

    assert acc.total_tokens == 0.0
    assert acc.total_cost == 0.0
    assert acc.calculated_cost == 0.0
    assert acc.has_tokens is False
    assert acc.has_cost is False
    assert acc.has_calculated_cost is False
    assert acc.timestamps == []
    assert acc.nodes_seen == set()
    assert acc.models_used == set()
    assert dict(acc.tokens_per_model) == {}
    assert acc.last_model is None


def test_mutable_defaults_are_independent_between_instances():
    acc1 = RowAccumulator()
    acc2 = RowAccumulator()

    acc1.timestamps.append(1.0)
    acc1.nodes_seen.add("Diagnostic")
    acc1.models_used.add("haiku")
    acc1.tokens_per_model["haiku"] += 10.0

    assert acc2.timestamps == []
    assert acc2.nodes_seen == set()
    assert acc2.models_used == set()
    assert dict(acc2.tokens_per_model) == {}


def test_tokens_per_model_is_a_defaultdict_of_float():
    acc = RowAccumulator()

    assert acc.tokens_per_model["unseen_model"] == 0.0