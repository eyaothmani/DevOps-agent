
from __future__ import annotations

import json
import json as _json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from langgraph.types import Command

from agent.config import settings
from agent.idempotency_lock import LockAcquisitionResult, LockOutcome
from agent.models import AlarmPayload, AlarmState, GraphState, JudgeVerdict, RCAResult
from agent.ssm_executor import SSMExecutionResult, SSMOutcome

RESULTS_FILE = Path(__file__).parent / "validation_results.json"


def _record(us: str, critere: str, ok: bool, evidence: str) -> None:
    entry = {
        "us": us,
        "critere": critere,
        "statut": "OK" if ok else "ECHEC",
        "evidence": evidence,
        "timestamp": time.time(),
    }
    existing = []
    if RESULTS_FILE.exists():
        existing = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    existing.append(entry)
    RESULTS_FILE.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    assert ok, f"[{us}] {critere} — NON VÉRIFIÉ : {evidence}"


@pytest.fixture(autouse=True, scope="session")
def _reset_results_file():
    if RESULTS_FILE.exists():
        RESULTS_FILE.unlink()


def _diagnostic_payload(
    confidence: int,
    action: str | None,
    reasoning=None,
    diagnosis="Test diagnosis",
):
    return json.dumps(
        {
            "diagnosis": diagnosis,
            "confidence": confidence,
            "reasoning_steps": reasoning or ["Étape de raisonnement test"],
            "suggested_action": action,
        }
    )


def _judge_payload(
    verdict: str, justification: str = "Analyse cohérente avec les logs."
):
    return json.dumps({"verdict": verdict, "justification": justification})


def _run_scenario(
    *,
    invoke_side_effects: list,
    kill_switch_enabled: bool = True,
    lock_acquired: bool = True,
    ssm_outcome: SSMOutcome = SSMOutcome.SUCCESS,
    alarm: AlarmPayload,
    mocked_graph,
    auto_resume: bool = True,
):

    mocked_graph.set_agent_enabled(kill_switch_enabled)

    if len(invoke_side_effects) >= 1:
        diag = _json.loads(invoke_side_effects[0])
        mocked_graph.set_rca(
            RCAResult(
                diagnosis=diag["diagnosis"],
                confidence=diag["confidence"],
                reasoning_steps=diag.get("reasoning_steps", []),
                suggested_action=diag["suggested_action"],
            )
        )

    if len(invoke_side_effects) >= 2:
        judge = _json.loads(invoke_side_effects[1])
        mocked_graph.set_judge(JudgeVerdict(judge["verdict"]))

    with (
        patch("agent.graph.nodes.decision_node._ssm_executor") as mock_ssm,
        patch("agent.graph.nodes.communication_node._slack_notifier") as mock_slack,
        patch(
            "agent.graph.nodes.decision_node._decision_dynamo_logger"
        ) as mock_dynamo_logger,
        patch("agent.graph.nodes.decision_node._idempotency_lock") as mock_lock,
    ):
        mock_ssm.run_and_wait.return_value = (
            "cmd-validation-suite",
            SSMExecutionResult(
                outcome=ssm_outcome, detail="Résultat simulé pour validation."
            ),
        )
        mock_lock.try_acquire_detailed.return_value = LockAcquisitionResult(
            outcome=(
                LockOutcome.ACQUIRED if lock_acquired else LockOutcome.ALREADY_HELD
            ),
            detail="mock",
        )
        mock_slack.channel = "#devops-alerts"
        mock_slack.send.return_value = None
        mock_dynamo_logger.log_node_contribution.return_value = True

        initial_state = GraphState(incident_id=alarm.incident_id, alarm=alarm)
        config = {"configurable": {"thread_id": alarm.incident_id}}
        result = mocked_graph.compiled.invoke({"state": initial_state}, config=config)
        interrupted = "__interrupt__" in result

        if interrupted and auto_resume:
            result = mocked_graph.compiled.invoke(
                Command(
                    resume={
                        "approved": True,
                        "validator": "test-harness",
                        "validated_at": "2026-08-01T00:00:00Z",
                    }
                ),
                config=config,
            )

        state = result["state"]

        return {
            "state": state,
            "interrupted": interrupted,
            "mock_dynamo_logger": mock_dynamo_logger,
            "mock_slack": mock_slack,
            "mock_ssm": mock_ssm,
            "mock_lock": mock_lock,
        }


def _slack_messages(mock_slack) -> list[str]:
    return [
        str(call.args) + str(call.kwargs) for call in mock_slack.send.call_args_list
    ]


def test_us3_1_action_autorisee_avec_contenu_complet_dynamo(mocked_graph):
    alarm = AlarmPayload(
        alarm_name="HighErrorRate-api-01",
        alarm_type="HighErrorRate",
        new_state=AlarmState.ALARM,
        instance_id="i-validation001",
    )
    ctx = _run_scenario(
        invoke_side_effects=[
            _diagnostic_payload(confidence=90, action="RollbackDeployment"),
            _judge_payload("coherent"),
        ],
        alarm=alarm,
        mocked_graph=mocked_graph,
    )
    decision = ctx["state"].decision
    _record(
        "US3.1",
        "action mappée via whitelist + exécutée via SSM",
        decision is not None and decision.status.value == "EXECUTED",
        f"decision.status={decision.status.value if decision else None}",
    )


def test_us3_1_action_refusee_par_whitelist_avec_motif(mocked_graph):
    alarm = AlarmPayload(
        alarm_name="CPUHigh-web-02",
        alarm_type="CPUHigh",
        new_state=AlarmState.ALARM,
        instance_id="i-validation002",
    )
    ctx = _run_scenario(
        invoke_side_effects=[
            _diagnostic_payload(confidence=90, action="RestartService"),
            _judge_payload("coherent"),
        ],
        alarm=alarm,
        mocked_graph=mocked_graph,
    )
    decision = ctx["state"].decision
    is_refused = decision is not None and "REFUS" in decision.status.value.upper()
    _record(
        "US3.1",
        "action refusée par whitelist si incohérente avec alarm_type",
        is_refused,
        f"decision.status={decision.status.value if decision else None}",
    )


def test_us3_2_message_slack_contient_les_4_elements_requis(mocked_graph):
    alarm = AlarmPayload(
        alarm_name="ServiceDown-web-03",
        alarm_type="ServiceDown",
        new_state=AlarmState.ALARM,
        instance_id="i-validation003",
    )
    ctx = _run_scenario(
        invoke_side_effects=[
            _diagnostic_payload(
                confidence=92,
                action="RestartService",
                diagnosis="Crash applicatif détecté",
            ),
            _judge_payload("coherent"),
        ],
        alarm=alarm,
        mocked_graph=mocked_graph,
    )
    messages = _slack_messages(ctx["mock_slack"])
    blob = " ".join(messages)

    _record(
        "US3.2",
        "message contient l'alerte initiale (alarm_name/alarm_type)",
        alarm.alarm_name in blob or alarm.alarm_type in blob,
        blob[:300],
    )
    _record(
        "US3.2",
        "message contient le diagnostic IA",
        "Crash applicatif" in blob,
        blob[:300],
    )
    _record(
        "US3.2",
        "message contient l'action entreprise",
        "RestartService" in blob,
        blob[:300],
    )
    _record(
        "US3.2",
        "message précise le niveau de confiance (critère backlog explicite)",
        "92" in blob or "confidence" in blob.lower() or "confiance" in blob.lower(),
        blob[:300],
    )


@pytest.mark.parametrize(
    "confidence,expected_executed",
    [(90, True), (95, True), (75, False), (84, False)],
)
def test_us4_1_seuil_85_respecte_dans_tous_les_cas(
    mocked_graph, confidence, expected_executed
):
    alarm = AlarmPayload(
        alarm_name=f"CPUHigh-seuil-{confidence}",
        alarm_type="CPUHigh",
        new_state=AlarmState.ALARM,
        instance_id=f"i-seuil-{confidence}",
    )
    ctx = _run_scenario(
        invoke_side_effects=[
            _diagnostic_payload(confidence=confidence, action="ScaleOut"),
            _judge_payload("coherent"),
        ],
        alarm=alarm,
        mocked_graph=mocked_graph,
        auto_resume=False,
    )
    decision = ctx["state"].decision
    if expected_executed:
        # >= seuil, action non risquée : exécution directe, aucune pause
        was_executed = decision is not None and decision.status.value == "EXECUTED"
        _record(
            "US4.1",
            f"seuil {settings.CONFIDENCE_THRESHOLD}% respecté pour confidence={confidence}",
            was_executed and not ctx["interrupted"],
            f"attendu EXECUTED sans pause, obtenu status={decision.status.value if decision else None}, "
            f"interrupted={ctx['interrupted']}.",
        )
    else:
        _record(
            "US4.1",
            f"seuil {settings.CONFIDENCE_THRESHOLD}% respecté pour confidence={confidence} "
            "(aucune exécution automatique sous le seuil)",
            ctx["interrupted"] and decision is None,
            f"interrupted={ctx['interrupted']}, decision={decision.status.value if decision else None}.",
        )


def test_us4_3_kill_switch_bloque_avant_diagnostic(mocked_graph):
    alarm = AlarmPayload(
        alarm_name="Test-KillSwitch",
        alarm_type="CPUHigh",
        new_state=AlarmState.ALARM,
        instance_id="i-killswitch",
    )
    ctx = _run_scenario(
        invoke_side_effects=[],
        kill_switch_enabled=False,
        alarm=alarm,
        mocked_graph=mocked_graph,
    )
    decision = ctx["state"].decision
    _record(
        "US4.3",
        "aucune action SSM exécutée quand désactivé",
        decision is not None and decision.status.value == "SKIPPED_KILL_SWITCH",
        f"decision.status={decision.status.value if decision else None}",
    )
    _record(
        "US4.3",
        "diagnostic jamais appelé (coupure avant analyse)",
        ctx["state"].rca is None,
        f"rca={ctx['state'].rca}",
    )


def test_us4_4_verrou_bloque_action_dupliquee(mocked_graph):
    alarm = AlarmPayload(
        alarm_name="Duplicate-CPUHigh",
        alarm_type="CPUHigh",
        new_state=AlarmState.ALARM,
        instance_id="i-dup",
    )
    ctx = _run_scenario(
        invoke_side_effects=[
            _diagnostic_payload(confidence=95, action="ScaleOut"),
            _judge_payload("coherent"),
        ],
        alarm=alarm,
        mocked_graph=mocked_graph,
        lock_acquired=False,
    )
    _record(
        "US4.4",
        "aucune ré-exécution SSM quand le verrou est déjà posé",
        ctx["mock_ssm"].run_and_wait.called is False,
        f"run_and_wait.called={ctx['mock_ssm'].run_and_wait.called}",
    )


def test_us4_9_desaccord_judge_degrade_la_confiance(mocked_graph):
    alarm = AlarmPayload(
        alarm_name="Judge-Disagreement",
        alarm_type="CPUHigh",
        new_state=AlarmState.ALARM,
        instance_id="i-judge",
    )
    ctx = _run_scenario(
        invoke_side_effects=[
            _diagnostic_payload(confidence=90, action="ScaleOut"),
            _judge_payload(
                "incoherent", "Le diagnostic ne s'appuie sur aucun log fourni."
            ),
        ],
        alarm=alarm,
        mocked_graph=mocked_graph,
        auto_resume=False,
    )
    decision = ctx["state"].decision
    _record(
        "US4.9",
        "désaccord juge/diagnostic empêche toute exécution automatique malgré confidence >= seuil",
        ctx["interrupted"] and decision is None,
        f"interrupted={ctx['interrupted']}, decision={decision.status.value if decision else None} "
        f"(confidence initiale=90, verdict juge=incoherent -> confiance dégradée sous le seuil -> validation requise)",
    )
