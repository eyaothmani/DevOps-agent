# tests/unit/test_decision_node_extra_coverage.py
"""
Tests complémentaires — agent/graph/nodes/decision_node.py

Cible précisément les branches signalées non couvertes par SonarCloud
(89.7% -> lignes rouges) et non déjà exercées par test_decision_node.py /
test_decision_node_closure.py :

  1. _handle_stale_freshness : verdict ALARM_WORSENED
     -> VALIDATION_STALE_RECONFIRMATION_REQUIRED
  2. _execute_remediation : lock_result.outcome == ACQUISITION_FAILED
     -> LOCK_ACQUISITION_FAILED
  3. _to_decimal_or_none : valeur déjà Decimal, et valeur d'un type
     inattendu (fallback)
  4. _log_decision : branche except (écriture de log best-effort qui
     échoue), pour le logger applicatif ET pour le logger Dynamo
  5. _rehydrate_state : state.rca / state.alarm fournis sous forme de
     dict (cas de reprise post-interrupt où LangGraph désérialise l'état)
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import agent.graph.nodes.decision_node as decn
from agent.graph.freshness import FreshnessCheckResult, FreshnessVerdict
from agent.idempotency_lock import LockAcquisitionResult, LockOutcome
from agent.models import (
    AlarmPayload,
    AlarmState,
    DecisionStatus,
    GraphState,
    HumanValidation,
    RCAResult,
)


def _make_state(
    alarm_type="ServiceDown",
    suggested_action="RestartService",
    instance_id="i-0123456789abcdef0",
    confidence=90,
):
    alarm = AlarmPayload(
        alarm_name=f"{alarm_type}-test",
        alarm_type=alarm_type,
        new_state=AlarmState.ALARM,
        instance_id=instance_id,
    )
    state = GraphState(incident_id=alarm.incident_id, alarm=alarm)
    state.rca = RCAResult(
        diagnosis="test",
        confidence=confidence,
        reasoning_steps=[],
        suggested_action=suggested_action,
    )
    return state


# ---------------------------------------------------------------------
# 1. _handle_stale_freshness — verdict ALARM_WORSENED
# ---------------------------------------------------------------------


class TestStaleFreshnessAlarmWorsened:
    def test_alarm_worsened_requires_retriage(self, monkeypatch):
        state = _make_state()
        human_validation = HumanValidation(
            approved=True,
            validator="alice",
            validated_at="2026-01-01T00:00:00Z",
            reason=None,
        )

        monkeypatch.setattr(
            decn,
            "check_still_relevant",
            lambda alarm, action: FreshnessCheckResult(
                verdict=FreshnessVerdict.ALARM_WORSENED,
                current_alarm_state="ALARM",
                detail="La situation s'est dégradée depuis le diagnostic initial.",
            ),
        )
        monkeypatch.setattr(decn, "_log_decision", lambda state: None)

        result = decn._finalize_decision(
            state=state,
            alarm=state.alarm,
            action=state.rca.suggested_action,
            human_validation=human_validation,
        )

        assert (
            result["state"].decision.status
            == DecisionStatus.VALIDATION_STALE_RECONFIRMATION_REQUIRED
        )
        assert result["state"].decision.human_validator == "alice"
        assert "dégradée" in result["state"].decision.detail


# ---------------------------------------------------------------------
# 2. _execute_remediation — verrou : ACQUISITION_FAILED
# ---------------------------------------------------------------------


class TestLockAcquisitionFailed:
    def test_lock_technical_failure_is_reported_distinctly(self, monkeypatch):
        state = _make_state()

        monkeypatch.setattr(decn, "is_allowed", lambda *_: True)
        monkeypatch.setattr(decn, "_log_decision", lambda state: None)

        mock_lock = MagicMock()
        mock_lock.try_acquire_detailed.return_value = LockAcquisitionResult(
            outcome=LockOutcome.ACQUISITION_FAILED,
            detail="Panne DynamoDB lors de l'acquisition du verrou.",
        )
        monkeypatch.setattr(decn, "_idempotency_lock", mock_lock)

        mock_ssm_executor = MagicMock()
        monkeypatch.setattr(decn, "_ssm_executor", mock_ssm_executor)

        result = decn._finalize_decision(
            state=state,
            alarm=state.alarm,
            action=state.rca.suggested_action,
            human_validation=None,
        )

        decision = result["state"].decision
        assert decision.status == DecisionStatus.LOCK_ACQUISITION_FAILED
        assert (
            decision.refusal_reason == "Panne DynamoDB lors de l'acquisition du verrou."
        )
        mock_ssm_executor.run_and_wait.assert_not_called()


# ---------------------------------------------------------------------
# 3. _to_decimal_or_none
# ---------------------------------------------------------------------


class TestToDecimalOrNone:
    def test_none_returns_none(self):
        assert decn._to_decimal_or_none(None) is None

    def test_int_is_converted(self):
        result = decn._to_decimal_or_none(3)
        assert result == Decimal(3)
        assert isinstance(result, Decimal)

    def test_float_is_converted(self):
        result = decn._to_decimal_or_none(1.25)
        assert result == Decimal("1.25")
        assert isinstance(result, Decimal)

    def test_existing_decimal_is_returned_as_is(self):
        value = Decimal("7.5")
        assert decn._to_decimal_or_none(value) is value

    def test_unexpected_type_falls_through_unchanged(self):
        # Branche de repli : ni None, ni Decimal, ni int/float (ex. une
        # chaîne déjà formatée) -> retournée telle quelle sans conversion.
        assert decn._to_decimal_or_none("N/A") == "N/A"


# ---------------------------------------------------------------------
# 4. _log_decision — branches except (best-effort, ne doit jamais lever)
# ---------------------------------------------------------------------


class TestLogDecisionExceptionHandling:
    def test_application_logger_failure_is_swallowed(self, monkeypatch):
        state = _make_state()
        state.decision = decn.DecisionResult(
            status=DecisionStatus.EXECUTED,
            action="RestartService",
            detail="ok",
        )

        mock_logger = MagicMock()
        mock_logger.info.side_effect = RuntimeError("logger HS")
        monkeypatch.setattr(decn, "_decision_logger", mock_logger)
        monkeypatch.setattr(decn, "_decision_dynamo_logger", MagicMock())

        # Ne doit lever aucune exception (best-effort).
        decn._log_decision(state)

        mock_logger.info.assert_called_once()

    def test_dynamo_logger_failure_is_swallowed(self, monkeypatch):
        state = _make_state()
        state.decision = decn.DecisionResult(
            status=DecisionStatus.EXECUTED,
            action="RestartService",
            detail="ok",
        )

        monkeypatch.setattr(decn, "_decision_logger", MagicMock())
        mock_dynamo_logger = MagicMock()
        mock_dynamo_logger.log_node_contribution.side_effect = RuntimeError("dynamo HS")
        monkeypatch.setattr(decn, "_decision_dynamo_logger", mock_dynamo_logger)

        # Ne doit lever aucune exception (best-effort) même si l'écriture
        # applicative a réussi mais l'écriture Dynamo échoue.
        decn._log_decision(state)

        mock_dynamo_logger.log_node_contribution.assert_called_once()


# ---------------------------------------------------------------------
# 5. _rehydrate_state — reprise post-interrupt (state désérialisé en dict)
# ---------------------------------------------------------------------


class TestRehydrateState:
    def test_dict_rca_and_alarm_are_rehydrated_into_models(self):
        state = _make_state()
        # Simule ce que LangGraph peut renvoyer après une désérialisation
        # de checkpoint : rca/alarm redevenus de simples dict.
        state.rca = state.rca.model_dump()
        state.alarm = state.alarm.model_dump()

        assert isinstance(state.rca, dict)
        assert isinstance(state.alarm, dict)

        decn._rehydrate_state(state)

        assert isinstance(state.rca, RCAResult)
        assert isinstance(state.alarm, AlarmPayload)
        assert state.rca.suggested_action == "RestartService"
        assert state.alarm.alarm_type == "ServiceDown"

    def test_already_hydrated_state_is_left_untouched(self):
        state = _make_state()
        rca_before = state.rca
        alarm_before = state.alarm

        decn._rehydrate_state(state)

        assert state.rca is rca_before
        assert state.alarm is alarm_before
