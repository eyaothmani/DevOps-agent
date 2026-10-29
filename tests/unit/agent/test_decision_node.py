# tests/unit/test_decision_node.py
from unittest.mock import patch

# NOTE (post-US 4.8) : decision_node() appelle désormais interrupt() dès
# qu'une validation humaine est requise. "RestartService" fait partie de
# RISKY_ACTIONS (cf. decision_node.py) et déclenche donc systématiquement
# interrupt(), quelle que soit la confiance — ce qui exige une boucle
# LangGraph avec checkpointer (voir tests/test_hitl_flow.py) et fait
# planter un appel direct avec `RuntimeError: Called get_config outside
# of a runnable context`.
#
# Ces tests-ci testent la logique d'exécution SSM / whitelist, pas le
# HITL : on appelle donc _finalize_decision() (le coeur métier, sans
# interrupt()) directement, avec human_validation=None.
from agent.graph.nodes.decision_node import _finalize_decision
from agent.idempotency_lock import LockAcquisitionResult, LockOutcome
from agent.models import AlarmPayload, AlarmState, GraphState, RCAResult
from agent.ssm_executor import SSMExecutionError, SSMExecutionResult, SSMOutcome


def _make_state(
    alarm_type="ServiceDown",
    suggested_action="RestartService",
    instance_id="i-0123456789abcdef0",
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
        confidence=90,
        reasoning_steps=[],
        suggested_action=suggested_action,
    )
    return state


def decision_node(payload: dict) -> dict:
    """Compat locale : reproduit l'ancien appel direct à decision_node()
    pour ces tests, en contournant interrupt() (hors sujet ici) via
    _finalize_decision()."""
    state = payload["state"]
    return _finalize_decision(
        state=state,
        alarm=state.alarm,
        action=state.rca.suggested_action,
        human_validation=None,
    )


def _lock_acquired():
    return LockAcquisitionResult(outcome=LockOutcome.ACQUIRED, detail="mock")


@patch("agent.graph.nodes.decision_node._idempotency_lock")
@patch("agent.graph.nodes.decision_node._decision_logger")
@patch("agent.graph.nodes.decision_node._ssm_executor")
def test_decision_executes_allowed_action(mock_ssm, mock_logger, mock_lock):
    mock_lock.try_acquire_detailed.return_value = _lock_acquired()
    mock_ssm.run_and_wait.return_value = (
        "cmd-123",
        SSMExecutionResult(
            outcome=SSMOutcome.SUCCESS, detail="Commande exécutée avec succès."
        ),
    )
    result = decision_node({"state": _make_state()})
    assert result["state"].decision.status.value == "EXECUTED"
    assert result["state"].decision.ssm_command_id == "cmd-123"
    mock_ssm.run_and_wait.assert_called_once()


@patch("agent.graph.nodes.decision_node._idempotency_lock")
@patch("agent.graph.nodes.decision_node._decision_logger")
@patch("agent.graph.nodes.decision_node._ssm_executor")
def test_decision_refuses_action_incoherente_avec_alarm_type(
    mock_ssm, mock_logger, mock_lock
):
    state = _make_state(alarm_type="CPUHigh", suggested_action="RollbackDeployment")
    result = decision_node({"state": state})
    assert result["state"].decision.status.value == "REFUSED_BY_WHITELIST"
    assert "non autorisée" in result["state"].decision.refusal_reason
    mock_ssm.run_and_wait.assert_not_called()


@patch("agent.graph.nodes.decision_node._idempotency_lock")
@patch("agent.graph.nodes.decision_node._decision_logger")
@patch("agent.graph.nodes.decision_node._ssm_executor")
def test_decision_refuses_when_no_instance_id(mock_ssm, mock_logger, mock_lock):
    result = decision_node({"state": _make_state(instance_id=None)})
    assert result["state"].decision.status.value == "REMEDIATION_UNAVAILABLE"
    assert "instance_id" in result["state"].decision.refusal_reason
    mock_ssm.run_and_wait.assert_not_called()


@patch("agent.graph.nodes.decision_node._idempotency_lock")
@patch("agent.graph.nodes.decision_node._decision_logger")
@patch("agent.graph.nodes.decision_node._ssm_executor")
def test_decision_handles_ssm_failure_gracefully(mock_ssm, mock_logger, mock_lock):
    mock_lock.try_acquire_detailed.return_value = _lock_acquired()
    mock_ssm.run_and_wait.side_effect = SSMExecutionError("Instance non gérée par SSM")
    result = decision_node({"state": _make_state()})
    assert result["state"].decision.status.value == "REMEDIATION_UNAVAILABLE"
    assert "Remédiation indisponible" in result["state"].decision.refusal_reason


@patch("agent.graph.nodes.decision_node._idempotency_lock")
@patch("agent.graph.nodes.decision_node._decision_logger")
@patch("agent.graph.nodes.decision_node._ssm_executor")
def test_decision_marks_execution_failed_when_command_fails_on_instance(
    mock_ssm, mock_logger, mock_lock
):
    mock_lock.try_acquire_detailed.return_value = _lock_acquired()
    mock_ssm.run_and_wait.return_value = (
        "cmd-456",
        SSMExecutionResult(
            outcome=SSMOutcome.FAILED,
            detail="Commande SSM en échec (voir StandardErrorContent).",
        ),
    )
    result = decision_node({"state": _make_state()})

    assert result["state"].decision.status.value == "EXECUTION_FAILED"
    assert "en échec" in result["state"].decision.refusal_reason
