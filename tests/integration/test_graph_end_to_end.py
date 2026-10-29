from unittest.mock import patch

from agent.models import AlarmPayload, AlarmState, GraphState, RCAResult
from agent.ssm_executor import SSMExecutionResult, SSMOutcome


def test_graph_runs_end_to_end(mocked_graph):
    # CPUHigh -> ScaleOut est la seule combinaison whitelistée qui n'est PAS
    # dans RISKY_ACTIONS (contrairement à RestartService/RollbackDeployment) :
    # c'est le seul chemin permettant une exécution SSM directe sans passer
    # par interrupt() (US 4.8), ce qui est l'objet de ce test "happy path".
    rca = RCAResult(
        diagnosis="Charge CPU anormale suite à un pic de trafic",
        confidence=88,
        reasoning_steps=["CPU > 80% depuis 5 min"],
        suggested_action="ScaleOut",
    )
    mocked_graph.set_rca(rca)

    with (
        patch("agent.graph.nodes.decision_node._ssm_executor") as mock_ssm,
        patch("agent.graph.nodes.communication_node._slack_notifier") as mock_slack,
    ):
        mock_ssm.run_and_wait.return_value = (
            "cmd-e2e-123",
            SSMExecutionResult(
                outcome=SSMOutcome.SUCCESS,
                detail="Commande exécutée avec succès.",
            ),
        )
        mock_slack.channel = "#devops-alerts"
        mock_slack.send.return_value = None

        alarm = AlarmPayload(
            alarm_name="CPUHigh-web-01",
            alarm_type="CPUHigh",
            new_state=AlarmState.ALARM,
            instance_id="i-0123456789abcdef0",
        )

        initial_state = GraphState(incident_id=alarm.incident_id, alarm=alarm)
        config = {"configurable": {"thread_id": alarm.incident_id}}
        result = mocked_graph.compiled.invoke({"state": initial_state}, config=config)
        final_state = result["state"]

        assert final_state.rca is not None
        assert final_state.rca.confidence == 88
        assert final_state.decision is not None
        assert final_state.decision.status.value == "EXECUTED"
        assert final_state.communication is not None
        assert final_state.communication.status.value == "SENT"
        assert len(final_state.trace) >= 3

        mock_ssm.run_and_wait.assert_called_once()
        mock_slack.send.assert_called_once()


def test_graph_survives_dynamo_failure(mocked_graph):
    # CORRECTION (post "pas de clôture implicite", voir models.py/decision_node.py) :
    # "NONE" n'est plus une valeur acceptée par RCAResult.suggested_action, ce
    # scénario ("action=NONE force toujours une validation humaine") n'existe
    # donc plus. On obtient le même effet ("le graphe suspend puis reprend
    # malgré une panne DynamoDB") avec une action de RISKY_ACTIONS
    # (RestartService) : elle déclenche interrupt() quelle que soit la
    # confiance (cf. decision_node._requires_human_validation), exactement
    # comme le faisait l'ancien scénario NONE — sans dépendre d'une valeur
    # qui n'existe plus dans le système.
    rca = RCAResult(
        diagnosis="Crash applicatif détecté",
        confidence=98,
        reasoning_steps=["Health check en échec"],
        suggested_action="RestartService",
    )
    mocked_graph.set_rca(rca)

    # ServiceDown est le seul alarm_type qui autorise RestartService dans la
    # whitelist (agent/graph/whitelist.py) : nécessaire pour atteindre EXECUTED
    # après approbation, plutôt que REFUSED_BY_WHITELIST.
    alarm = AlarmPayload(
        alarm_name="Test",
        alarm_type="ServiceDown",
        new_state=AlarmState.ALARM,
        instance_id="i-0123456789abcdef0",
    )
    initial_state = GraphState(incident_id=alarm.incident_id, alarm=alarm)
    config = {"configurable": {"thread_id": alarm.incident_id}}

    # Simuler une panne du logger DynamoDB (patch local) : le node doit
    # rester best-effort et ne jamais interrompre le flux principal (US 2.4).
    with patch(
        "agent.graph.nodes.decision_node._decision_dynamo_logger.log_node_contribution",
        side_effect=Exception("DynamoDB indisponible"),
    ):
        # --- Étape 1 : première invocation -> suspension attendue ---
        result = mocked_graph.compiled.invoke({"state": initial_state}, config=config)
        assert "__interrupt__" in result, (
            "une action de RISKY_ACTIONS doit toujours déclencher une validation humaine"
        )

        # --- Étape 2 : reprise après approbation ---
        from langgraph.types import Command

        resumed = mocked_graph.compiled.invoke(
            Command(
                resume={
                    "approved": True,
                    "validator": "test-manuel",
                    "validated_at": "2026-08-02T08:32:29Z",
                }
            ),
            config=config,
        )
        final_state = resumed["state"]

        assert final_state.rca is not None
        assert final_state.decision is not None
        # Malgré l'échec simulé du logger DynamoDB (best-effort, US 2.4), le
        # graphe va bien jusqu'au bout de la remédiation après approbation.
        assert final_state.decision.status.value == "EXECUTED"
