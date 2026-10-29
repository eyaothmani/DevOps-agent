"""
conftest.py
-----------
Fixtures partagées pour les tests HITL (US 4.7 / US 4.8).
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

import agent.graph.freshness as fr
import agent.graph.nodes.communication_node as cn
import agent.graph.nodes.decision_node as decn
import agent.graph.nodes.diagnostic_node as dn
import agent.graph.nodes.judge_node as jn
import agent.graph.nodes.kill_switch_node as ksn
from agent.graph.state import AgentState
from agent.idempotency_lock import LockAcquisitionResult, LockOutcome
from agent.models import JudgeResult, JudgeVerdict, RCAResult
from agent.ssm_executor import SSMOutcome


class _FakeSSMResult:
    def __init__(self, outcome=SSMOutcome.SUCCESS, detail="ok"):
        self.outcome = outcome
        self.detail = detail


@pytest.fixture
def rca_factory():
    def _make(
        confidence=95,
        action="ScaleOut",
        diagnosis="CPU saturé par un process zombie",
    ):
        return RCAResult(
            diagnosis=diagnosis,
            confidence=confidence,
            suggested_action=action,
            reasoning_steps=[
                "cpu > 90% pendant 5 min",
                "aucun déploiement récent",
            ],
            model_id="anthropic.claude-haiku-4-5-20251001-v1:0",
        )

    return _make


@pytest.fixture
def mocked_graph(monkeypatch, rca_factory):
    state_holder = {
        "rca": rca_factory(),
        "judge": JudgeVerdict.COHERENT,
        "ssm_outcome": SSMOutcome.SUCCESS,
        "freshness": fr.FreshnessVerdict.STILL_RELEVANT,
    }

    # IMPORTANT : on patche la CLASSE (type(ksn._kill_switch)), jamais
    # l'instance singleton ksn._kill_switch directement. monkeypatch.setattr
    # sur une instance capture la bound method existante (résolue via la
    # classe) et la RÉ-INJECTE en attribut d'instance à la restauration —
    # cet attribut d'instance masque alors PERMANENTEMENT tout patch de
    # classe fait par les tests suivants (unittest.mock.patch compris),
    # pour le reste de la session pytest.
    monkeypatch.setattr(type(ksn._kill_switch), "is_agent_enabled", lambda self: True)
    monkeypatch.setattr(
        ksn._decision_logger, "log_node_contribution", lambda **kw: True
    )

    def fake_diagnostic(agent_state):
        state = agent_state["state"]
        state.rca = state_holder["rca"]
        state.add_trace("Diagnostic", "mock")
        return {"state": state}

    monkeypatch.setattr(dn, "diagnostic_node", fake_diagnostic)

    monkeypatch.setattr(
        jn._bedrock_client,
        "judge",
        lambda **kw: JudgeResult(verdict=state_holder["judge"], justification="mock"),
    )
    monkeypatch.setattr(jn._decision_logger, "log_node_contribution", lambda **kw: True)

    monkeypatch.setattr(
        decn._decision_dynamo_logger,
        "log_node_contribution",
        lambda **kw: True,
    )
    # try_acquire (legacy) est conservé pour les anciens appelants, mais
    # decision_node.py appelle désormais try_acquire_detailed() (US 4.4) :
    # les deux doivent être mockés, sinon try_acquire_detailed non patché
    # retombe sur l'implémentation réelle (appel DynamoDB réel).
    monkeypatch.setattr(decn._idempotency_lock, "try_acquire", lambda **kw: True)
    monkeypatch.setattr(
        decn._idempotency_lock,
        "try_acquire_detailed",
        lambda **kw: LockAcquisitionResult(outcome=LockOutcome.ACQUIRED, detail="mock"),
    )
    monkeypatch.setattr(decn._idempotency_lock, "release", lambda **kw: None)
    monkeypatch.setattr(
        decn,
        "check_still_relevant",
        lambda alarm, action: fr.FreshnessCheckResult(
            verdict=state_holder["freshness"],
            current_alarm_state="ALARM",
            detail="mock",
        ),
    )
    monkeypatch.setattr(
        decn._ssm_executor, "send_command", lambda *a, **kw: "cmd-mock-123"
    )
    monkeypatch.setattr(
        decn._ssm_executor,
        "wait_for_result",
        lambda *a, **kw: _FakeSSMResult(outcome=state_holder["ssm_outcome"]),
    )
    # run_and_wait() est le point d'entrée réel appelé par decision_node.py ;
    # il route en interne vers send_command/wait_for_result (documents
    # "Command") OU vers start_automation/wait_for_automation (documents
    # "Automation", ex. Custom-ScaleOutASG pour l'action ScaleOut). Mocker
    # uniquement send_command/wait_for_result laisse échapper le chemin
    # Automation vers un vrai appel AWS. On mocke donc run_and_wait
    # directement pour couvrir les deux chemins de façon uniforme.
    monkeypatch.setattr(
        decn._ssm_executor,
        "run_and_wait",
        lambda *a, **kw: (
            "cmd-mock-123",
            _FakeSSMResult(outcome=state_holder["ssm_outcome"]),
        ),
    )

    # On NE remplace PAS communication_node par un fake : la vraie fonction
    # construit le message (diagnostic, action, résultat, confiance) à
    # partir de l'état — c'est ce contenu que test_epic3_epic4_full_workflow
    # vérifie. Seul l'appel réseau (_slack_notifier.send) est mocké, pas
    # la logique de formatage du message.
    monkeypatch.setattr(cn._slack_notifier, "send", lambda *a, **kw: None)
    monkeypatch.setattr(cn._slack_notifier, "channel", "#devops-alerts")

    builder = StateGraph(AgentState)
    builder.add_node("kill_switch", ksn.kill_switch_node)
    builder.add_node("diagnostic", dn.diagnostic_node)
    builder.add_node("judge", jn.judge_node)
    builder.add_node("decision", decn.decision_node)
    builder.add_node("communication", cn.communication_node)
    builder.add_edge(START, "kill_switch")
    builder.add_conditional_edges(
        "kill_switch",
        ksn.route_after_kill_switch,
        {"continue": "diagnostic", "stop": "communication"},
    )
    builder.add_edge("diagnostic", "judge")
    builder.add_edge("judge", "decision")
    builder.add_edge("decision", "communication")
    builder.add_edge("communication", END)

    class _Handle:
        compiled = builder.compile(checkpointer=MemorySaver())

        @staticmethod
        def set_rca(rca):
            state_holder["rca"] = rca

        @staticmethod
        def set_judge(verdict):
            state_holder["judge"] = verdict

        @staticmethod
        def set_ssm_outcome(outcome):
            state_holder["ssm_outcome"] = outcome

        @staticmethod
        def set_freshness(verdict):
            state_holder["freshness"] = verdict

        @staticmethod
        def set_agent_enabled(enabled: bool):
            monkeypatch.setattr(
                type(ksn._kill_switch),
                "is_agent_enabled",
                lambda self: enabled,
            )

        @property
        def slack_mock(self):
            return cn._slack_notifier

        @property
        def ssm_mock(self):
            return decn._ssm_executor

        @property
        def dynamo_logger_mock(self):
            return decn._decision_dynamo_logger

        @property
        def lock_mock(self):
            return decn._idempotency_lock

    return _Handle()
