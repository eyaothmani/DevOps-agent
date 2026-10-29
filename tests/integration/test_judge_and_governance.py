# tests/test_judge_and_governance.py
"""
Tests de gouvernance pour l'Epic 4 :
- US 4.9 : le juge indépendant (LLM-as-judge) doit pouvoir forcer une
  escalade humaine en cas de désaccord avec le diagnostic initial, même
  si la confiance initiale dépasse le seuil (85%).
- US 4.4 : le verrou d'idempotence doit bloquer toute action en double
  sur la même ressource.

Historique de validation (important pour le rapport de tests, US 5.4) :
- Une première hypothèse supposait que decision_node devait lire un champ
  `state.judge_result` pour décider d'escalader. Ce champ n'existe pas
  dans l'implémentation réelle.
- Le vrai mécanisme, découvert en lisant judge_node.py, est différent et
  plus simple : en cas de désaccord (verdict INCOHERENT alors que
  confidence >= seuil), judge_node dégrade directement rca.confidence à
  (CONFIDENCE_THRESHOLD - 1). decision_node, qui vérifie déjà
  `rca.confidence < CONFIDENCE_THRESHOLD` avant toute autre logique,
  déclenche alors naturellement LOW_CONFIDENCE_SKIPPED — sans avoir
  besoin de connaître l'existence du juge. Les tests ci-dessous valident
  ce mécanisme réel plutôt qu'un mécanisme hypothétique.
"""

from unittest.mock import MagicMock, patch

from agent.config import settings
from agent.graph.nodes import judge_node as judge_node_module
from agent.graph.nodes.decision_node import _idempotency_lock, decision_node
from agent.graph.nodes.judge_node import judge_node
from agent.idempotency_lock import LockAcquisitionResult, LockOutcome
from agent.models import AlarmPayload, AlarmState, JudgeResult, JudgeVerdict, RCAResult


def make_alarm(instance_id="i-test", alarm_type="CPUHigh"):
    return AlarmPayload(
        alarm_name="test-alarm",
        alarm_type=alarm_type,
        new_state=AlarmState.ALARM,
        instance_id=instance_id,
    )


# ── Test 1 : le juge est bien appelé et son verdict est loggé ───────────────
def test_judge_node_invokes_bedrock_and_logs_verdict():
    """
    Vérifie que judge_node appelle bien le client Bedrock (méthode .judge())
    et journalise le verdict + la justification dans DynamoDB via
    _decision_logger.log_node_contribution.

    En conditions réelles, on a déjà la preuve que ce comportement
    fonctionne (22 verdicts motivés trouvés dans agent_decisions avec
    judge_verdict + judge_justification). Ce test le rend reproductible
    sans dépendre d'un vrai incident AWS.
    """
    with (
        patch.object(judge_node_module._bedrock_client, "judge") as mock_judge,
        patch.object(
            judge_node_module._decision_logger, "log_node_contribution"
        ) as mock_log,
    ):
        mock_judge.return_value = JudgeResult(
            verdict=JudgeVerdict.COHERENT,
            justification="Diagnostic cohérent avec les logs fournis.",
        )

        state = MagicMock()
        state.rca = RCAResult(
            diagnosis="test", confidence=90, suggested_action="RestartService"
        )
        state.logs = []
        state.incident_id = "test-incident-judge"

        result = judge_node({"state": state})

        mock_judge.assert_called_once()
        mock_log.assert_called_once()
        _, kwargs = mock_log.call_args
        assert kwargs["extra"]["judge_verdict"] == "coherent"
        # Confidence inchangée : pas de désaccord ici (verdict cohérent)
        assert result["state"].rca.confidence == 90


# ── Test 2 : désaccord juge/diagnostic dégrade la confiance sous le seuil ───
def test_judge_disagreement_degrades_confidence_below_threshold():
    """
    Critère d'acceptation US 4.9 : si confidence >= seuil mais le juge
    retourne 'incoherent', la confiance doit être ramenée sous le seuil
    (CONFIDENCE_THRESHOLD - 1), forçant ainsi l'escalade en aval dans
    decision_node sans que celui-ci ait besoin de connaître le juge.
    """
    with (
        patch.object(judge_node_module._bedrock_client, "judge") as mock_judge,
        patch.object(judge_node_module._decision_logger, "log_node_contribution"),
    ):
        mock_judge.return_value = JudgeResult(
            verdict=JudgeVerdict.INCOHERENT,
            justification="Contredit les logs fournis.",
        )

        state = MagicMock()
        state.rca = RCAResult(
            diagnosis="test", confidence=90, suggested_action="RestartService"
        )
        state.logs = []
        state.incident_id = "test-incident-judge-2"

        result = judge_node({"state": state})

        assert result["state"].rca.confidence == settings.CONFIDENCE_THRESHOLD - 1
        assert result["state"].rca.confidence < settings.CONFIDENCE_THRESHOLD


# ── Test 3 (intégration) : le désaccord du juge se propage jusqu'à l'escalade
#    réelle dans decision_node, sans mock de la logique de décision ─────────
def test_judge_disagreement_propagates_to_decision_escalation(
    mocked_graph, rca_factory
):
    """
    Test de bout en bout (sans appel réseau) : on exécute le graphe complet
    (kill_switch -> diagnostic -> judge -> decision -> communication) pour
    prouver que le désaccord du juge se propage bien jusqu'à une escalade
    humaine réelle.

    NOTE (post-US 4.8) : avant l'ajout du HITL natif, decision_node posait
    directement un statut LOW_CONFIDENCE_SKIPPED dès que la confiance
    passait sous le seuil. Ce n'est plus le comportement réel : decision_node
    appelle désormais interrupt() dans ce cas (pause pour validation
    humaine), ce qui EST l'escalade attendue par l'US 4.9 — plus riche que
    l'ancien skip silencieux. interrupt() exigeant une boucle LangGraph
    avec checkpointer, on ne peut plus enchaîner judge_node/decision_node
    en appels Python directs (cf. RuntimeError: Called get_config outside
    of a runnable context) : on passe donc par le graphe réel avec
    MemorySaver fourni par la fixture mocked_graph (tests/integration/conftest.py).
    """
    # confidence=95 >= seuil (85) : sans désaccord, pas d'interruption.
    # C'est justement le désaccord du juge (mocked_graph.set_judge) qui doit
    # dégrader la confiance sous le seuil et déclencher l'escalade.
    mocked_graph.set_rca(rca_factory(confidence=95, action="RestartService"))
    mocked_graph.set_judge(JudgeVerdict.INCOHERENT)

    config = {"configurable": {"thread_id": "test-incident-e2e"}}
    alarm = make_alarm()
    from agent.models import GraphState

    initial = GraphState(incident_id="test-incident-e2e", alarm=alarm)

    result = mocked_graph.compiled.invoke({"state": initial}, config=config)

    # Le graphe doit s'être arrêté sur une interruption (validation humaine
    # requise), pas avoir posé un statut final directement.
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["confidence"] == settings.CONFIDENCE_THRESHOLD - 1
    assert payload["judge_verdict"] == "incoherent"


# ── Test 4 : verrou d'idempotence bloque une action en double ───────────────
def test_duplicate_action_skipped_by_idempotency_lock():
    """
    Reproduit en local le cas DUPLICATE_ACTION_SKIPPED déjà observé en
    conditions réelles (incident e28f0d3a, 18h22) — pour le rendre
    reproductible sans dépendre d'un vrai incident AWS.
    """
    with patch.object(
        _idempotency_lock,
        "try_acquire_detailed",
        return_value=LockAcquisitionResult(
            outcome=LockOutcome.ALREADY_HELD, detail="mock"
        ),
    ):
        state = MagicMock()
        state.alarm = make_alarm()
        state.rca = RCAResult(
            diagnosis="test", confidence=95, suggested_action="ScaleOut"
        )
        state.incident_id = "test-incident-dup"

        result = decision_node({"state": state})

        assert result["state"].decision.status.value == "DUPLICATE_ACTION_SKIPPED"
