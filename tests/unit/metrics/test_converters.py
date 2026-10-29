"""Unit tests for evaluation.metrics.converters."""

from __future__ import annotations

from decimal import Decimal

import pytest

from evaluation.metrics.converters import (
    calculate_model_cost,
    derive_model_used,
    derive_status,
    parse_timestamp,
    resolution_seconds,
    to_float,
)

# ---------------------------------------------------------------------
# to_float
# ---------------------------------------------------------------------


class TestToFloat:
    def test_decimal(self):
        assert to_float(Decimal("2.5")) == 2.5

    def test_string(self):
        assert to_float("3") == 3.0

    def test_int(self):
        assert to_float(3) == 3.0

    def test_invalid_string(self):
        assert to_float("abc") is None

    def test_none(self):
        assert to_float(None) is None


# ---------------------------------------------------------------------
# derive_status
# ---------------------------------------------------------------------


class TestDeriveStatus:
    def test_decision_status_preferred(self):
        record = {
            "decision_status": "EXECUTED",
            "communication_status": "SENT",
        }
        assert derive_status(record) == "EXECUTED"

    def test_falls_back_to_communication_status(self):
        assert derive_status({"communication_status": "SENT"}) == "SENT"

    def test_none_when_absent(self):
        assert derive_status({}) is None

    def test_empty_decision_status_falls_back(self):
        record = {"decision_status": "", "communication_status": "SENT"}
        assert derive_status(record) == "SENT"


# ---------------------------------------------------------------------
# derive_model_used
# ---------------------------------------------------------------------


class TestDeriveModelUsed:
    @pytest.mark.parametrize(
        "model_id,expected",
        [
            ("anthropic.claude-3-haiku-x", "haiku"),
            ("anthropic.claude-3-sonnet-x", "sonnet"),
            ("anthropic.claude-3-opus-x", "opus"),
            ("weird-model", "weird-model"),
        ],
    )
    def test_family_detection(self, model_id, expected):
        assert derive_model_used({"model_id": model_id}) == expected

    def test_none_when_absent(self):
        assert derive_model_used({}) is None

    def test_none_when_empty(self):
        assert derive_model_used({"model_id": ""}) is None


# ---------------------------------------------------------------------
# parse_timestamp
# ---------------------------------------------------------------------


class TestParseTimestamp:
    def test_none(self):
        assert parse_timestamp(None) is None

    def test_numeric(self):
        result = parse_timestamp(1700000000)
        assert result is not None
        assert result.year == 2023

    def test_decimal(self):
        assert parse_timestamp(Decimal(1700000000)) is not None

    def test_iso_string_with_z_suffix(self):
        result = parse_timestamp("2024-01-01T00:00:00Z")
        assert result is not None
        assert result.year == 2024

    def test_iso_string_naive_gets_utc(self):
        result = parse_timestamp("2024-01-01T00:00:00")
        assert result is not None
        assert result.tzinfo is not None

    def test_invalid_string(self):
        assert parse_timestamp("not-a-date") is None

    def test_invalid_type(self):
        assert parse_timestamp(object()) is None

    def test_out_of_range_numeric(self):
        assert parse_timestamp(10**20) is None


# ---------------------------------------------------------------------
# calculate_model_cost
# ---------------------------------------------------------------------


class TestCalculateModelCost:
    def test_known_model(self):
        from evaluation.metrics.config import PRICE_PER_TOKEN

        assert calculate_model_cost(1000, "haiku") == 1000 * PRICE_PER_TOKEN["haiku"]

    def test_unknown_model_uses_default_price(self):
        from evaluation.metrics.config import PRICE_PER_TOKEN

        assert calculate_model_cost(1000, "gpt-x") == 1000 * PRICE_PER_TOKEN["default"]


# ---------------------------------------------------------------------
# resolution_seconds
# ---------------------------------------------------------------------


class TestResolutionSeconds:
    def test_single_write_returns_none(self):
        item = {
            "nb_node_writes": 1,
            "alert_received_at": "2026-08-09T10:00:00+00:00",
            "resolved_at": "2026-08-09T10:00:30+00:00",
        }
        assert resolution_seconds(item) is None

    def test_missing_node_writes_returns_none(self):
        assert resolution_seconds({}) is None

    def test_missing_timestamps_returns_none(self):
        item = {"nb_node_writes": 3}
        assert resolution_seconds(item) is None

    def test_invalid_timestamps_returns_none(self):
        item = {
            "nb_node_writes": 3,
            "alert_received_at": "invalid",
            "resolved_at": "also-invalid",
        }
        assert resolution_seconds(item) is None

    def test_computes_positive_delta(self):
        item = {
            "nb_node_writes": 3,
            "alert_received_at": "2026-08-09T10:00:00+00:00",
            "resolved_at": "2026-08-09T10:00:30+00:00",
        }
        assert resolution_seconds(item) == 30.0

    def test_negative_delta_returns_none(self):
        item = {
            "nb_node_writes": 3,
            "alert_received_at": "2026-08-09T10:01:00+00:00",
            "resolved_at": "2026-08-09T10:00:00+00:00",
        }
        assert resolution_seconds(item) is None

    def test_falls_back_to_first_last_timestamp(self):
        item = {
            "nb_node_writes": 2,
            "first_timestamp": 1000.0,
            "last_timestamp": 1030.0,
        }
        assert resolution_seconds(item) == 30.0

    def test_falls_back_to_action_completed_at(self):
        item = {
            "nb_node_writes": 2,
            "alert_received_at": "2026-08-09T10:00:00+00:00",
            "action_completed_at": "2026-08-09T10:00:15+00:00",
        }
        assert resolution_seconds(item) == 15.0