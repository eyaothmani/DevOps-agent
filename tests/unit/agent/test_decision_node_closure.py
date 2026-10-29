import time
from unittest.mock import MagicMock

from agent.graph.nodes.decision_node import _finalize_decision
from agent.idempotency_lock import LockAcquisitionResult, LockOutcome
from agent.models import DecisionStatus
from agent.ssm_executor import SSMOutcome


def call_decision(payload: dict) -> dict:
    """Reproduit l'ancien appel `decision_node(payload)` pour ces tests,
    en contournant interrupt() (hors sujet ici) via _finalize_decision()."""
    state = payload["state"]
    return _finalize_decision(
        state=state,
        alarm=state.alarm,
        action=state.rca.suggested_action,
        human_validation=None,
    )


class FakeAlarm:
    def __init__(
        self, instance_id=None, alarm_type="ServiceDown", alarm_name="ServiceDown-test"
    ):
        self.instance_id = instance_id
        self.alarm_type = alarm_type
        self.alarm_name = alarm_name


class FakeRCA:
    def __init__(self, suggested_action="RollbackDeployment", confidence=90):
        self.suggested_action = suggested_action
        self.confidence = confidence


class FakeState:
    def __init__(self, incident_id="inc-test-0001", alarm=None, rca=None):
        self.incident_id = incident_id
        self.alarm = alarm or FakeAlarm()
        self.rca = rca or FakeRCA()
        self.decision = None
        self.trace = []

    def add_trace(self, node, msg):
        self.trace.append((node, msg))


class FakeSSMResult:
    """Simule la valeur retournée par SSMExecutor.wait_for_result()."""

    def __init__(self, outcome, detail="OK", duration_seconds=None):
        self.outcome = outcome
        self.detail = detail
        # Champ hypothétique : si SSMExecutor expose une durée, c'est
        # potentiellement la source manquante de resolution_time_seconds.
        self.duration_seconds = duration_seconds


def make_payload(alarm=None, rca=None, incident_id="inc-test-0001"):
    return {"state": FakeState(incident_id=incident_id, alarm=alarm, rca=rca)}


# ============================================================================
# US 3.1 — resolution_time_seconds réellement calculé
# ============================================================================


class TestUS31ResolutionTime:
    def test_resolution_time_seconds_is_not_none_on_successful_execution(
        self, monkeypatch
    ):

        # Arrange
        mock_ssm_executor = MagicMock()

        def slow_run_and_wait(*args, **kwargs):
            time.sleep(0.05)  # simule un polling SSM non instantané
            return "cmd-test-001", FakeSSMResult(
                outcome=SSMOutcome.SUCCESS,
                detail="Commande exécutée avec succès",
            )

        mock_ssm_executor.run_and_wait.side_effect = slow_run_and_wait
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node._ssm_executor", mock_ssm_executor
        )

        mock_lock = MagicMock()
        mock_lock.try_acquire_detailed.return_value = LockAcquisitionResult(
            outcome=LockOutcome.ACQUIRED, detail="mock"
        )
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node._idempotency_lock", mock_lock
        )

        monkeypatch.setattr(
            "agent.graph.nodes.decision_node.is_allowed", lambda *_: True
        )
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node.get_ssm_document",
            lambda action: "AWS-RollbackDeployment",
        )
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node._decision_dynamo_logger",
            MagicMock(),
        )
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node.settings.CONFIDENCE_THRESHOLD", 85
        )

        # FIX : un instance_id doit être fourni, sinon FakeAlarm() par
        # défaut vaut instance_id=None et le test tombe dans le garde-fou
        # REMEDIATION_UNAVAILABLE avant même d'atteindre SSM.
        payload = make_payload(
            alarm=FakeAlarm(instance_id="i-abc123"),
            rca=FakeRCA(suggested_action="RollbackDeployment", confidence=90),
        )

        # Act
        result = call_decision(payload)

        # Assert
        state = result["state"]
        assert state.decision.status == DecisionStatus.EXECUTED
        assert state.decision.resolution_time_seconds is not None, ()
        assert state.decision.resolution_time_seconds >= 0.05, ()

    def test_resolution_time_seconds_is_none_when_refused_by_whitelist(
        self, monkeypatch
    ):
        """Cas légitime distinct du bug : aucune exécution -> pas de durée."""
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node.is_allowed", lambda *_: False
        )
        mock_ssm_executor = MagicMock()
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node._ssm_executor", mock_ssm_executor
        )
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node._decision_dynamo_logger",
            MagicMock(),
        )
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node.settings.CONFIDENCE_THRESHOLD", 85
        )

        payload = make_payload(
            rca=FakeRCA(suggested_action="DeleteDatabase", confidence=95)
        )

        result = call_decision(payload)
        state = result["state"]

        assert state.decision.status == DecisionStatus.REFUSED_BY_WHITELIST
        assert state.decision.resolution_time_seconds is None
        mock_ssm_executor.run_and_wait.assert_not_called()

    def test_resolution_time_seconds_is_none_when_missing_instance_id(
        self, monkeypatch
    ):

        monkeypatch.setattr(
            "agent.graph.nodes.decision_node.is_allowed", lambda *_: True
        )
        mock_ssm_executor = MagicMock()
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node._ssm_executor", mock_ssm_executor
        )
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node._decision_dynamo_logger",
            MagicMock(),
        )
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node.settings.CONFIDENCE_THRESHOLD", 85
        )

        payload = make_payload(alarm=FakeAlarm(instance_id=None))

        result = call_decision(payload)
        state = result["state"]

        assert state.decision.status == DecisionStatus.REMEDIATION_UNAVAILABLE
        assert state.decision.resolution_time_seconds is None
        assert "instance_id" in state.decision.detail
        mock_ssm_executor.run_and_wait.assert_not_called()

    # ============================================================================
    # US 4.4 — orchestration du verrou d'idempotence par decision_node
    # ============================================================================

    def test_duplicate_action_skipped_when_lock_not_acquired(self, monkeypatch):
        # Arrange
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node.is_allowed", lambda *_: True
        )
        mock_ssm_executor = MagicMock()
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node._ssm_executor", mock_ssm_executor
        )

        mock_lock = MagicMock()
        mock_lock.try_acquire_detailed.return_value = LockAcquisitionResult(
            outcome=LockOutcome.ALREADY_HELD, detail="mock: verrou déjà détenu"
        )
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node._idempotency_lock", mock_lock
        )
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node._decision_dynamo_logger",
            MagicMock(),
        )
        monkeypatch.setattr(
            "agent.graph.nodes.decision_node.settings.CONFIDENCE_THRESHOLD", 85
        )

        # FIX : instance_id requis, sinon le garde-fou REMEDIATION_UNAVAILABLE
        # intercepte avant même que le verrou soit consulté.
        payload = make_payload(alarm=FakeAlarm(instance_id="i-abc123"))

        # Act
        result = call_decision(payload)
        state = result["state"]

        # Assert
        assert state.decision.status == DecisionStatus.DUPLICATE_ACTION_SKIPPED
        mock_ssm_executor.run_and_wait.assert_not_called()
        mock_lock.release.assert_not_called()
