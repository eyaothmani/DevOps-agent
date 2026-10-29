from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from agent.ssm_executor import (
    AUTOMATION_DOCUMENTS,
    SSMExecutionError,
    SSMExecutor,
    SSMOutcome,
)


def client_error(code: str, message: str = "boom") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, "SomeOperation")


@pytest.fixture(autouse=True)
def fast_clock(monkeypatch):
    """Neutralise les vrais délais : time.sleep() ne dort pas, et
    time.monotonic() avance de façon négligeable à chaque appel, pour que
    les boucles de polling ne dépassent jamais la deadline par hasard.
    Les tests qui veulent spécifiquement simuler un TIMED_OUT
    surchargent time.monotonic eux-mêmes (voir test_*_timed_out_no_status)."""
    monkeypatch.setattr("agent.ssm_executor.time.sleep", lambda *_: None)
    counter = {"t": 0.0}

    def fake_monotonic():
        counter["t"] += 0.001
        return counter["t"]

    monkeypatch.setattr("agent.ssm_executor.time.monotonic", fake_monotonic)
    return counter


@pytest.fixture
def executor():
    mock_client = MagicMock()
    return SSMExecutor(client=mock_client), mock_client


# ---------------------------------------------------------------------
# send_command() — envoi (documents "Command")
# ---------------------------------------------------------------------


class TestSendCommand:
    def test_instance_not_managed_raises(self, executor):
        exec_, client = executor
        client.describe_instance_information.return_value = {
            "InstanceInformationList": []
        }

        with pytest.raises(SSMExecutionError, match="non gérée par SSM Agent"):
            exec_.send_command("i-123", "AWS-RunShellScript", action="RestartService")

        client.send_command.assert_not_called()

    def test_instance_managed_offline_raises(self, executor):
        exec_, client = executor
        client.describe_instance_information.return_value = {
            "InstanceInformationList": [{"PingStatus": "ConnectionLost"}]
        }
        with pytest.raises(SSMExecutionError):
            exec_.send_command("i-123", "AWS-RunShellScript", action="RestartService")

    def test_describe_instance_information_error_fails_open(self, executor):
        """Si la vérification préalable échoue techniquement, on tente quand
        même l'envoi plutôt que de bloquer toute remédiation (best-effort)."""
        exec_, client = executor
        client.describe_instance_information.side_effect = client_error("Throttling")
        client.send_command.return_value = {"Command": {"CommandId": "cmd-1"}}

        command_id = exec_.send_command(
            "i-123", "AWS-RunShellScript", action="RestartService"
        )

        assert command_id == "cmd-1"

    def test_run_shell_script_injects_action_parameters(self, executor):
        exec_, client = executor
        client.describe_instance_information.return_value = {
            "InstanceInformationList": [{"PingStatus": "Online"}]
        }
        client.send_command.return_value = {"Command": {"CommandId": "cmd-42"}}

        command_id = exec_.send_command(
            "i-123", "AWS-RunShellScript", action="RestartService"
        )

        assert command_id == "cmd-42"
        _, kwargs = client.send_command.call_args
        assert kwargs["InstanceIds"] == ["i-123"]
        assert kwargs["DocumentName"] == "AWS-RunShellScript"
        assert "systemctl restart mon-service-demo" in " ".join(
            kwargs["Parameters"]["commands"]
        )

    def test_run_shell_script_unknown_action_refuses_empty_command(self, executor):
        """Garde-fou : on n'envoie jamais AWS-RunShellScript sans commandes
        (ce qui exécuterait un no-op silencieux plutôt que d'échouer)."""
        exec_, client = executor
        client.describe_instance_information.return_value = {
            "InstanceInformationList": [{"PingStatus": "Online"}]
        }

        with pytest.raises(SSMExecutionError, match="Aucune commande shell"):
            exec_.send_command("i-123", "AWS-RunShellScript", action="ActionInconnue")

        client.send_command.assert_not_called()

    def test_non_shell_document_sent_without_parameters(self, executor):
        """Custom-RollbackDeployment n'a pas de branche ACTION_TO_SHELL_COMMANDS :
        aucun Parameters injecté, le document embarque déjà son script."""
        exec_, client = executor
        client.describe_instance_information.return_value = {
            "InstanceInformationList": [{"PingStatus": "Online"}]
        }
        client.send_command.return_value = {"Command": {"CommandId": "cmd-7"}}

        exec_.send_command(
            "i-123", "Custom-RollbackDeployment", action="RollbackDeployment"
        )

        _, kwargs = client.send_command.call_args
        assert "Parameters" not in kwargs

    def test_send_command_access_denied(self, executor):
        exec_, client = executor
        client.describe_instance_information.return_value = {
            "InstanceInformationList": [{"PingStatus": "Online"}]
        }
        client.send_command.side_effect = client_error("AccessDeniedException")

        with pytest.raises(SSMExecutionError, match="Accès refusé"):
            exec_.send_command(
                "i-123",
                "Custom-RollbackDeployment",
                action="RollbackDeployment",
            )

    def test_send_command_generic_client_error(self, executor):
        """Reproduit exactement l'incident réel : InvalidDocument levée par
        l'API si on lui envoie par erreur un document Automation."""
        exec_, client = executor
        client.describe_instance_information.return_value = {
            "InstanceInformationList": [{"PingStatus": "Online"}]
        }
        client.send_command.side_effect = client_error(
            "InvalidDocument",
            "Document type provided is not supported. Only type: 'Command' is supported for run command.",
        )

        with pytest.raises(SSMExecutionError, match="Échec technique SendCommand"):
            exec_.send_command("i-123", "Custom-ScaleOutASG", action="ScaleOut")


# ---------------------------------------------------------------------
# wait_for_result() — suivi (documents "Command")
# ---------------------------------------------------------------------


class TestWaitForResult:
    @pytest.mark.parametrize(
        "status,expected_outcome",
        [
            ("Success", SSMOutcome.SUCCESS),
            ("Cancelled", SSMOutcome.CANCELLED),
            ("TimedOut", SSMOutcome.SSM_REPORTED_TIMEOUT),
        ],
    )
    def test_terminal_statuses(self, executor, status, expected_outcome):
        exec_, client = executor
        client.get_command_invocation.return_value = {"Status": status}

        result = exec_.wait_for_result("cmd-1", "i-123")

        assert result.outcome is expected_outcome

    def test_failed_status_uses_stderr_as_detail(self, executor):
        exec_, client = executor
        client.get_command_invocation.return_value = {
            "Status": "Failed",
            "StandardErrorContent": "systemctl: command not found",
        }

        result = exec_.wait_for_result("cmd-1", "i-123")

        assert result.outcome is SSMOutcome.FAILED
        assert "systemctl" in result.detail

    def test_unrecognized_status_is_failed(self, executor):
        exec_, client = executor
        client.get_command_invocation.return_value = {"Status": "SomethingWeird"}

        result = exec_.wait_for_result("cmd-1", "i-123")

        assert result.outcome is SSMOutcome.FAILED
        assert "SomethingWeird" in result.detail

    def test_pending_then_success(self, executor):
        exec_, client = executor
        client.get_command_invocation.side_effect = [
            {"Status": "Pending"},
            {"Status": "InProgress"},
            {"Status": "Success"},
        ]

        result = exec_.wait_for_result("cmd-1", "i-123")

        assert result.outcome is SSMOutcome.SUCCESS
        assert client.get_command_invocation.call_count == 3

    def test_invocation_does_not_exist_is_retried(self, executor):
        """Race condition connue : juste après send_command, l'invocation
        peut ne pas encore exister côté API — on retente plutôt que
        d'échouer immédiatement."""
        exec_, client = executor
        client.get_command_invocation.side_effect = [
            client_error("InvocationDoesNotExist"),
            {"Status": "Success"},
        ]

        result = exec_.wait_for_result("cmd-1", "i-123")

        assert result.outcome is SSMOutcome.SUCCESS

    def test_access_denied_during_polling(self, executor):
        exec_, client = executor
        client.get_command_invocation.side_effect = client_error(
            "AccessDeniedException"
        )

        result = exec_.wait_for_result("cmd-1", "i-123")

        assert result.outcome is SSMOutcome.ACCESS_DENIED

    def test_deadline_exceeded_without_terminal_status(self, executor, monkeypatch):
        exec_, client = executor
        # 1er appel monotonic() = baseline utilisée pour calculer la
        # deadline ; tout appel suivant renvoie une valeur bien supérieure,
        # pour que la 1re comparaison "time.monotonic() < deadline" échoue.
        monkeypatch.setattr(
            "agent.ssm_executor.time.monotonic",
            MagicMock(side_effect=[0.0, 10_000.0]),
        )

        result = exec_.wait_for_result("cmd-1", "i-123")

        assert result.outcome is SSMOutcome.TIMED_OUT
        client.get_command_invocation.assert_not_called()


# ---------------------------------------------------------------------
# start_automation() / wait_for_automation() — documents "Automation"
# ---------------------------------------------------------------------


class TestAutomation:
    def test_start_automation_success_returns_execution_id(self, executor):
        exec_, client = executor
        client.start_automation_execution.return_value = {
            "AutomationExecutionId": "auto-1"
        }

        execution_id = exec_.start_automation("Custom-ScaleOutASG")

        assert execution_id == "auto-1"
        _, kwargs = client.start_automation_execution.call_args
        assert kwargs["DocumentName"] == "Custom-ScaleOutASG"

    def test_start_automation_without_parameters_omits_parameters_key(self, executor):
        """RÉGRESSION (bug trouvé en stress test réel, non détecté par un
        mock naïf) : StartAutomationExecution rejette un `Parameters`
        explicitement vide ({}) avec une ValidationException côté AWS
        ("Member must have length greater than or equal to 1"). La clé
        doit être OMISE de l'appel quand il n'y a rien à surcharger, pour
        laisser le document utiliser ses propres valeurs par défaut
        (AutoScalingGroupName / DesiredCapacity)."""
        exec_, client = executor
        client.start_automation_execution.return_value = {
            "AutomationExecutionId": "auto-1"
        }

        exec_.start_automation("Custom-ScaleOutASG")

        _, kwargs = client.start_automation_execution.call_args
        assert "Parameters" not in kwargs

    def test_start_automation_with_explicit_parameters_are_passed_through(
        self, executor
    ):
        exec_, client = executor
        client.start_automation_execution.return_value = {
            "AutomationExecutionId": "auto-2"
        }

        exec_.start_automation(
            "Custom-ScaleOutASG", parameters={"DesiredCapacity": ["5"]}
        )

        _, kwargs = client.start_automation_execution.call_args
        assert kwargs["Parameters"] == {"DesiredCapacity": ["5"]}

    def test_start_automation_access_denied(self, executor):
        exec_, client = executor
        client.start_automation_execution.side_effect = client_error(
            "AccessDeniedException"
        )

        with pytest.raises(SSMExecutionError, match="Accès refusé"):
            exec_.start_automation("Custom-ScaleOutASG")

    def test_start_automation_generic_error(self, executor):
        exec_, client = executor
        client.start_automation_execution.side_effect = client_error(
            "ValidationException"
        )

        with pytest.raises(SSMExecutionError, match="StartAutomationExecution"):
            exec_.start_automation("Custom-ScaleOutASG")

    @pytest.mark.parametrize(
        "status,expected_outcome",
        [
            ("Success", SSMOutcome.SUCCESS),
            ("Cancelled", SSMOutcome.CANCELLED),
            ("TimedOut", SSMOutcome.SSM_REPORTED_TIMEOUT),
        ],
    )
    def test_wait_for_automation_terminal_statuses(
        self, executor, status, expected_outcome
    ):
        exec_, client = executor
        client.get_automation_execution.return_value = {
            "AutomationExecution": {"AutomationExecutionStatus": status}
        }

        result = exec_.wait_for_automation("auto-1")

        assert result.outcome is expected_outcome

    def test_wait_for_automation_failed_uses_failure_message(self, executor):
        exec_, client = executor
        client.get_automation_execution.return_value = {
            "AutomationExecution": {
                "AutomationExecutionStatus": "Failed",
                "FailureMessage": "autoscaling:SetDesiredCapacity refusé (IAM)",
            }
        }

        result = exec_.wait_for_automation("auto-1")

        assert result.outcome is SSMOutcome.FAILED
        assert "SetDesiredCapacity" in result.detail

    def test_wait_for_automation_pending_then_success(self, executor):
        exec_, client = executor
        client.get_automation_execution.side_effect = [
            {"AutomationExecution": {"AutomationExecutionStatus": "Pending"}},
            {"AutomationExecution": {"AutomationExecutionStatus": "InProgress"}},
            {"AutomationExecution": {"AutomationExecutionStatus": "Success"}},
        ]

        result = exec_.wait_for_automation("auto-1")

        assert result.outcome is SSMOutcome.SUCCESS
        assert client.get_automation_execution.call_count == 3

    def test_wait_for_automation_access_denied(self, executor):
        exec_, client = executor
        client.get_automation_execution.side_effect = client_error(
            "AccessDeniedException"
        )

        result = exec_.wait_for_automation("auto-1")

        assert result.outcome is SSMOutcome.ACCESS_DENIED

    def test_wait_for_automation_unrecognized_status(self, executor):
        exec_, client = executor
        client.get_automation_execution.return_value = {
            "AutomationExecution": {"AutomationExecutionStatus": "Weird"}
        }

        result = exec_.wait_for_automation("auto-1")

        assert result.outcome is SSMOutcome.FAILED

    def test_wait_for_automation_deadline_exceeded(self, executor, monkeypatch):
        exec_, client = executor
        monkeypatch.setattr(
            "agent.ssm_executor.time.monotonic",
            MagicMock(side_effect=[0.0, 10_000.0]),
        )

        result = exec_.wait_for_automation("auto-1")

        assert result.outcome is SSMOutcome.TIMED_OUT
        client.get_automation_execution.assert_not_called()


# ---------------------------------------------------------------------
# run_and_wait() — routage Command vs Automation (le point corrigé)
# ---------------------------------------------------------------------


class TestRunAndWaitRouting:
    def test_scaleout_routes_to_automation_path(self, executor):
        """Cas exact de l'incident réel : ScaleOut -> Custom-ScaleOutASG,
        déclaré 'Automation' -> doit passer par start_automation_execution,
        jamais par send_command (qui provoquait InvalidDocument)."""
        exec_, client = executor
        client.start_automation_execution.return_value = {
            "AutomationExecutionId": "auto-99"
        }
        client.get_automation_execution.return_value = {
            "AutomationExecution": {"AutomationExecutionStatus": "Success"}
        }

        execution_id, result = exec_.run_and_wait(
            "i-123", "Custom-ScaleOutASG", action="ScaleOut"
        )

        assert execution_id == "auto-99"
        assert result.outcome is SSMOutcome.SUCCESS
        client.start_automation_execution.assert_called_once()
        client.send_command.assert_not_called()
        client.get_command_invocation.assert_not_called()

    def test_restart_service_routes_to_command_path(self, executor):
        exec_, client = executor
        client.describe_instance_information.return_value = {
            "InstanceInformationList": [{"PingStatus": "Online"}]
        }
        client.send_command.return_value = {"Command": {"CommandId": "cmd-55"}}
        client.get_command_invocation.return_value = {"Status": "Success"}

        command_id, result = exec_.run_and_wait(
            "i-123", "AWS-RunShellScript", action="RestartService"
        )

        assert command_id == "cmd-55"
        assert result.outcome is SSMOutcome.SUCCESS
        client.start_automation_execution.assert_not_called()
        client.get_automation_execution.assert_not_called()

    def test_rollback_routes_to_command_path(self, executor):
        exec_, client = executor
        client.describe_instance_information.return_value = {
            "InstanceInformationList": [{"PingStatus": "Online"}]
        }
        client.send_command.return_value = {"Command": {"CommandId": "cmd-77"}}
        client.get_command_invocation.return_value = {
            "Status": "Failed",
            "StandardErrorContent": "err",
        }

        command_id, result = exec_.run_and_wait(
            "i-123", "Custom-RollbackDeployment", action="RollbackDeployment"
        )

        assert command_id == "cmd-77"
        assert result.outcome is SSMOutcome.FAILED

    def test_automation_documents_set_matches_whitelist_mapping(self):
        """Garde-fou anti-régression : si un jour quelqu'un ajoute un nouveau
        document Automation dans whitelist.py sans l'ajouter ici, ce test
        casse au lieu de faire échouer un incident en production."""
        from agent.graph.whitelist import ACTION_TO_SSM_DOCUMENT

        assert AUTOMATION_DOCUMENTS.issubset(set(ACTION_TO_SSM_DOCUMENT.values()))
        assert "Custom-ScaleOutASG" in AUTOMATION_DOCUMENTS
        assert "AWS-RunShellScript" not in AUTOMATION_DOCUMENTS
        assert "Custom-RollbackDeployment" not in AUTOMATION_DOCUMENTS
