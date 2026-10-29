"""
US 4.5 — Routage intelligent des modèles (FinOps)

Vérifie que le node Diagnostic :
1. Appelle Haiku en premier (modèle par défaut, léger/peu cher).
2. N'escalade PAS vers Sonnet si la confiance de Haiku est suffisante
   (>= ROUTING_ESCALATION_THRESHOLD).
3. Escalade vers Sonnet si la confiance de Haiku est insuffisante
   (< ROUTING_ESCALATION_THRESHOLD), et que le résultat final est bien
   celui de Sonnet (pas celui de Haiku).
4. Le model_id effectivement utilisé est propagé jusqu'au logging
   DynamoDB (agent_decisions), pour permettre la comparaison de coût.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.config import settings
from agent.graph.nodes.diagnostic_node import diagnostic_node
from agent.models import RCAResult


def _make_rca(confidence: int, model_id: str) -> RCAResult:
    return RCAResult(
        diagnosis="Cause probable détectée",
        confidence=confidence,
        reasoning_steps=["indice 1", "indice 2"],
        suggested_action="ScaleOut",
        model_id=model_id,
        tokens_used=123,
    )


def _make_agent_state(incident_id="inc-test-finops"):
    from agent.graph.state import GraphState
    from agent.models import AlarmPayload, AlarmState

    alarm = AlarmPayload(
        incident_id=incident_id,
        alarm_name="agent-devops-cpu-high",
        alarm_type="CPUHigh",
        new_state=AlarmState.ALARM,
        instance_id="i-0123456789abcdef0",
        timestamp="2026-07-23T10:00:00Z",
    )
    state = GraphState(incident_id=incident_id, alarm=alarm)
    return {"state": state}


@pytest.fixture(autouse=True)
def _patch_logs_and_groundedness():
    """Isole le node des vraies dépendances CloudWatch / groundedness."""
    with (
        patch("agent.graph.nodes.diagnostic_node.fetch_recent_logs", return_value=[]),
        patch(
            "agent.graph.nodes.diagnostic_node.format_logs_for_prompt",
            return_value="logs...",
        ),
        patch(
            "agent.graph.nodes.diagnostic_node.compute_groundedness_score",
            return_value=0.9,
        ),
    ):
        yield


def test_no_escalation_when_haiku_confidence_high():
    """Haiku suffisamment confiant (>= seuil) => pas de second appel Sonnet."""
    haiku_result = _make_rca(confidence=90, model_id=settings.BEDROCK_MODEL_ID)

    mock_client = MagicMock()
    mock_client.diagnose.return_value = haiku_result

    with (
        patch("agent.graph.nodes.diagnostic_node._bedrock_client", mock_client),
        patch("agent.graph.nodes.diagnostic_node._decision_logger", MagicMock()),
    ):
        result = diagnostic_node(_make_agent_state())

    assert mock_client.diagnose.call_count == 1
    assert result["state"].rca.model_id == settings.BEDROCK_MODEL_ID
    assert result["state"].rca.confidence == 90


def test_escalation_when_haiku_confidence_low():
    """Haiku peu confiant (< seuil) => second appel Sonnet, résultat final = Sonnet."""
    haiku_result = _make_rca(confidence=30, model_id=settings.BEDROCK_MODEL_ID)
    sonnet_result = _make_rca(confidence=88, model_id=settings.BEDROCK_SONNET_MODEL_ID)

    mock_client = MagicMock()
    mock_client.diagnose.side_effect = [haiku_result, sonnet_result]

    with (
        patch("agent.graph.nodes.diagnostic_node._bedrock_client", mock_client),
        patch("agent.graph.nodes.diagnostic_node._decision_logger", MagicMock()),
    ):
        result = diagnostic_node(_make_agent_state())

    assert mock_client.diagnose.call_count == 2

    _, second_call_kwargs = mock_client.diagnose.call_args_list[1]
    assert second_call_kwargs.get("model_id") == settings.BEDROCK_SONNET_MODEL_ID

    assert result["state"].rca.model_id == settings.BEDROCK_SONNET_MODEL_ID
    assert result["state"].rca.confidence == 88


def test_model_id_propagated_to_dynamo_logging():
    """Le model_id effectivement utilisé doit être écrit dans agent_decisions
    (US 4.5, critère : 'le modèle utilisé ... stocké dans agent_decisions')."""
    sonnet_result = _make_rca(confidence=85, model_id=settings.BEDROCK_SONNET_MODEL_ID)
    haiku_result = _make_rca(confidence=20, model_id=settings.BEDROCK_MODEL_ID)

    mock_client = MagicMock()
    mock_client.diagnose.side_effect = [haiku_result, sonnet_result]
    mock_logger = MagicMock()

    with (
        patch("agent.graph.nodes.diagnostic_node._bedrock_client", mock_client),
        patch("agent.graph.nodes.diagnostic_node._decision_logger", mock_logger),
    ):
        diagnostic_node(_make_agent_state())

    _, log_kwargs = mock_logger.log_node_contribution.call_args
    assert log_kwargs["extra"]["model_id"] == settings.BEDROCK_SONNET_MODEL_ID
