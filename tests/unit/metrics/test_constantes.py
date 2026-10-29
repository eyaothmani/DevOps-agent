"""Unit tests for evaluation.metrics.constants."""

from __future__ import annotations

from evaluation.metrics import constants as c


def test_status_string_values():
    assert c.STATUS_AWAITING_HUMAN_VALIDATION == "AWAITING_HUMAN_VALIDATION"
    assert c.STATUS_VALIDATION_TIMEOUT_CANCELLED == "VALIDATION_TIMEOUT_ACTION_CANCELLED"
    assert c.STATUS_REJECTED_BY_HUMAN == "REJECTED_BY_HUMAN"
    assert c.STATUS_VALIDATION_STALE_SKIPPED == "VALIDATION_STALE_ACTION_SKIPPED"
    assert c.STATUS_DUPLICATE_ACTION_SKIPPED == "DUPLICATE_ACTION_SKIPPED"
    assert c.STATUS_REFUSED_BY_WHITELIST == "REFUSED_BY_WHITELIST"
    assert c.STATUS_REMEDIATION_UNAVAILABLE == "REMEDIATION_UNAVAILABLE"
    assert c.STATUS_EXECUTED == "EXECUTED"
    assert c.STATUS_AUTO_REMEDIATED == "AUTO_REMEDIATED"
    assert c.STATUS_LOW_CONFIDENCE_SKIPPED == "LOW_CONFIDENCE_SKIPPED"
    assert c.STATUS_JUDGE_DISAGREEMENT_ESCALATED == "JUDGE_DISAGREEMENT_ESCALATED"


def test_success_statuses():
    assert c.SUCCESS_STATUSES == {
        c.STATUS_EXECUTED,
        c.STATUS_AUTO_REMEDIATED,
    }


def test_escalation_statuses():
    assert c.ESCALATION_STATUSES == {
        c.STATUS_AWAITING_HUMAN_VALIDATION,
        c.STATUS_VALIDATION_TIMEOUT_CANCELLED,
        c.STATUS_REJECTED_BY_HUMAN,
        c.STATUS_VALIDATION_STALE_SKIPPED,
        c.STATUS_LOW_CONFIDENCE_SKIPPED,
        c.STATUS_JUDGE_DISAGREEMENT_ESCALATED,
    }


def test_guardrail_trigger_statuses():
    assert c.GUARDRAIL_TRIGGER_STATUSES == {
        c.STATUS_DUPLICATE_ACTION_SKIPPED,
        c.STATUS_REFUSED_BY_WHITELIST,
    }


def test_failure_statuses():
    assert c.FAILURE_STATUSES == {c.STATUS_REMEDIATION_UNAVAILABLE}


def test_statuses_exclus_dashboard():
    assert c.STATUSES_EXCLUS_DASHBOARD == {c.STATUS_REMEDIATION_UNAVAILABLE}


def test_summed_fields():
    assert c.SUMMED_FIELDS == {"tokens_used", "estimated_cost_usd"}


def test_timestamp_field():
    assert c.TIMESTAMP_FIELD == "timestamp"


def test_skip_fields():
    assert c.SKIP_FIELDS == {"incident_id", "node_timestamp"}


def test_core_nodes_required():
    assert c.CORE_NODES_REQUIRED == {"Diagnostic", "Decision", "Communication"}