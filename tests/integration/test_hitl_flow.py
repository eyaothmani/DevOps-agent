"""
test_hitl_flow.py
------------------
US 4.8 — Tests du human-in-the-loop natif (interrupt LangGraph).

Zéro appel AWS réel : tous les effets de bord sont mockés (cf. conftest.py).
"""

from __future__ import annotations

from langgraph.types import Command

from agent.graph.freshness import FreshnessVerdict
from agent.models import AlarmPayload, AlarmState, DecisionStatus, GraphState


def _alarm(alarm_type="CPUHigh", instance_id="i-0123456789"):
    return AlarmPayload(
        alarm_name="cpu-high-test",
        alarm_type=alarm_type,
        new_state=AlarmState.ALARM,
        instance_id=instance_id,
    )


def _run_until_interrupt(mocked_graph, incident_id: str, alarm: AlarmPayload):
    config = {"configurable": {"thread_id": incident_id}}
    initial = GraphState(incident_id=incident_id, alarm=alarm)
    result = mocked_graph.compiled.invoke({"state": initial}, config=config)
    return result, config


def test_low_confidence_triggers_interrupt(mocked_graph, rca_factory):
    mocked_graph.set_rca(rca_factory(confidence=40, action="ScaleOut"))
    alarm = _alarm()
    result, _ = _run_until_interrupt(mocked_graph, "inc-low-conf", alarm)
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["proposed_action"] == "ScaleOut"
    assert payload["confidence"] == 40
    assert payload["judge_verdict"] == "coherent"


def test_high_confidence_non_risky_skips_interrupt(mocked_graph, rca_factory):
    mocked_graph.set_rca(rca_factory(confidence=95, action="ScaleOut"))
    alarm = _alarm()
    result, _ = _run_until_interrupt(mocked_graph, "inc-high-conf", alarm)
    assert "__interrupt__" not in result
    assert result["state"].decision.status == DecisionStatus.EXECUTED
    assert result["state"].decision.human_validator is None


def test_risky_action_triggers_interrupt_even_with_high_confidence(
    mocked_graph, rca_factory
):
    mocked_graph.set_rca(rca_factory(confidence=99, action="RollbackDeployment"))
    alarm = _alarm(alarm_type="HighErrorRate")
    result, _ = _run_until_interrupt(mocked_graph, "inc-risky", alarm)
    assert "__interrupt__" in result


def test_approved_resumes_and_executes(mocked_graph, rca_factory):
    mocked_graph.set_rca(rca_factory(confidence=40, action="ScaleOut"))
    alarm = _alarm(alarm_type="CPUHigh")
    _, config = _run_until_interrupt(mocked_graph, "inc-approved", alarm)

    result = mocked_graph.compiled.invoke(
        Command(
            resume={
                "approved": True,
                "validator": "alice",
                "validated_at": "2026-07-30T10:00:00Z",
            }
        ),
        config=config,
    )
    decision = result["state"].decision
    assert decision.status == DecisionStatus.EXECUTED
    assert decision.human_validator == "alice"
    assert decision.human_validated_at == "2026-07-30T10:00:00Z"
    assert decision.ssm_command_id == "cmd-mock-123"
    assert result["state"].communication.status.value == "SENT"


def test_rejected_by_human(mocked_graph, rca_factory):
    mocked_graph.set_rca(rca_factory(confidence=40, action="ScaleOut"))
    alarm = _alarm()
    _, config = _run_until_interrupt(mocked_graph, "inc-rejected", alarm)

    result = mocked_graph.compiled.invoke(
        Command(
            resume={
                "approved": False,
                "validator": "bob",
                "validated_at": "2026-07-30T10:05:00Z",
                "reason": "Faux positif connu",
            }
        ),
        config=config,
    )
    decision = result["state"].decision
    assert decision.status == DecisionStatus.REJECTED_BY_HUMAN
    assert decision.human_validator == "bob"


def test_timeout_cancels_action(mocked_graph, rca_factory):
    mocked_graph.set_rca(rca_factory(confidence=40, action="ScaleOut"))
    alarm = _alarm()
    _, config = _run_until_interrupt(mocked_graph, "inc-timeout", alarm)

    result = mocked_graph.compiled.invoke(
        Command(
            resume={
                "approved": False,
                "validator": "system_timeout",
                "validated_at": "2026-07-30T10:20:00Z",
                "reason": "Timeout de validation",
            }
        ),
        config=config,
    )
    assert (
        result["state"].decision.status
        == DecisionStatus.VALIDATION_TIMEOUT_ACTION_CANCELLED
    )


def test_freshness_alarm_resolved_blocks_approved_action(mocked_graph, rca_factory):
    mocked_graph.set_rca(rca_factory(confidence=40, action="ScaleOut"))
    mocked_graph.set_freshness(FreshnessVerdict.ALARM_RESOLVED)
    alarm = _alarm()
    _, config = _run_until_interrupt(mocked_graph, "inc-stale-resolved", alarm)

    result = mocked_graph.compiled.invoke(
        Command(
            resume={
                "approved": True,
                "validator": "alice",
                "validated_at": "2026-07-30T10:00:00Z",
            }
        ),
        config=config,
    )
    decision = result["state"].decision
    assert decision.status == DecisionStatus.VALIDATION_STALE_ACTION_SKIPPED
    assert decision.ssm_command_id is None


def test_whitelist_refusal_after_approval_keeps_audit_trail(mocked_graph, rca_factory):
    """Ce test échoue tant que decision_node ne propage pas le resume.
    Voir correction à appliquer dans decision_node.py."""
    mocked_graph.set_rca(rca_factory(confidence=40, action="RestartService"))
    alarm = _alarm(alarm_type="CPUHigh")
    _, config = _run_until_interrupt(
        mocked_graph, "inc-whitelist-after-approval", alarm
    )

    result = mocked_graph.compiled.invoke(
        Command(
            resume={
                "approved": True,
                "validator": "alice",
                "validated_at": "2026-07-30T10:00:00Z",
            }
        ),
        config=config,
    )
    decision = result["state"].decision
    assert decision.status == DecisionStatus.REFUSED_BY_WHITELIST
    assert decision.human_validator == "alice"  # attendu, mais échoue actuellement


# NOTE : l'ancien test_no_action_needs_human_confirmation_when_uncertain a été
# supprimé. Il vérifiait qu'une action "NONE" à confiance incertaine déclenche
# une validation humaine puis aboutit à NO_ACTION_CONFIRMED_BY_HUMAN. Ce
# chemin n'existe plus structurellement : RCAResult.suggested_action rejette
# désormais "NONE" (models.py), et decision_node.py lève explicitement
# ValueError si action == "NONE". Le scénario "confiance faible -> interrupt ->
# approbation -> exécution" qu'il recoupait partiellement reste couvert par
# test_approved_resumes_and_executes ci-dessus.


def test_kill_switch_bypasses_diagnostic_and_hitl_entirely(mocked_graph, rca_factory):
    mocked_graph.set_agent_enabled(False)
    alarm = _alarm()
    result, _ = _run_until_interrupt(mocked_graph, "inc-kill-switch", alarm)
    assert "__interrupt__" not in result
    assert result["state"].decision.status == DecisionStatus.SKIPPED_KILL_SWITCH
    assert result["state"].rca is None