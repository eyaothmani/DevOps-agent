"""Fixtures partagées pour les tests de evaluation.manage_table."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_table():
    """Table DynamoDB factice — deux incidents, plusieurs lignes par node.

    Reflète le format réel : chaque node (diagnostic, decision,
    communication) écrit sa propre ligne, différenciée par node_timestamp.
    merge_items_by_incident() les fusionne ensuite, et derive_status /
    derive_model_used dérivent "status" et "model_used" à partir des
    champs bruts (decision_status, model_id).

    inc-1 : CPUHigh, EXECUTED, modèle Sonnet.
    inc-2 : ServiceDown, REFUSED_BY_WHITELIST, modèle Haiku.
    """
    table = MagicMock()
    table.table_name = "agent_decisions"
    table.key_schema = [{"AttributeName": "incident_id", "KeyType": "HASH"}]
    table.scan.return_value = {
        "Items": [
            # --- inc-1 : CPUHigh, exécuté, Sonnet ---
            {
                "incident_id": "inc-1",
                "node_timestamp": "diagnostic#2026-07-01T09:00:00Z",
                "alarm_type": "CPUHigh",
                "timestamp": "2026-07-01T09:00:00Z",
                "confidence": 90,
                "model_id": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                "groundedness_score": 1.0,
                "judge_verdict": "coherent",
                "tokens_used": 300,
                "estimated_cost_usd": 0.006,
            },
            {
                "incident_id": "inc-1",
                "node_timestamp": "decision#2026-07-01T09:00:05Z",
                "decision_status": "EXECUTED",
                "tokens_used": 100,
                "estimated_cost_usd": 0.002,
            },
            {
                "incident_id": "inc-1",
                "node_timestamp": "communication#2026-07-01T09:00:10Z",
                "resolved_at": "2026-07-01T09:00:10Z",
                "action_completed_at": "2026-07-01T09:00:09Z",
                "tokens_used": 50,
                "estimated_cost_usd": 0.001,
            },
            # --- inc-2 : ServiceDown, refusé par la whitelist, Haiku ---
            {
                "incident_id": "inc-2",
                "node_timestamp": "diagnostic#2026-07-01T10:00:00Z",
                "alarm_type": "ServiceDown",
                "timestamp": "2026-07-01T10:00:00Z",
                "confidence": 60,
                "model_id": "anthropic.claude-3-5-haiku-20241022-v1:0",
                "groundedness_score": 0.5,
                "tokens_used": 150,
                "estimated_cost_usd": 0.001,
            },
            {
                "incident_id": "inc-2",
                "node_timestamp": "decision#2026-07-01T10:00:05Z",
                "decision_status": "REFUSED_BY_WHITELIST",
                "tokens_used": 80,
                "estimated_cost_usd": 0.0008,
            },
        ]
    }
    return table