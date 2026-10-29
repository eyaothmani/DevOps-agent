from __future__ import annotations

import dataclasses
import enum
import logging
import time

import boto3
from botocore.exceptions import ClientError

from agent.config import settings

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = {"Success", "Failed", "Cancelled", "TimedOut"}
_PENDING_STATUSES = {"Pending", "InProgress", "Delayed", "Cancelling"}

# Documents SSM de type "Automation" (ex. Custom-ScaleOutASG, voir
# infra/ssm_documents.tf : document_type = "Automation"). Ces documents
# n'acceptent PAS send_command() / InstanceIds — l'API SSM les rejette
# avec "Document type provided is not supported. Only type: 'Command'
# is supported for run command." Ils doivent être lancés via
# start_automation_execution() et suivis via get_automation_execution().
AUTOMATION_DOCUMENTS: set[str] = {"Custom-ScaleOutASG"}

_AUTOMATION_PENDING_STATUSES = {
    "Pending",
    "InProgress",
    "Waiting",
    "Cancelling",
}

ACTION_TO_SHELL_COMMANDS: dict[str, list[str]] = {
    "RestartService": [
        "echo '--- Avant redémarrage ---'",
        "systemctl status mon-service-demo --no-pager || true",
        "sudo systemctl restart mon-service-demo",
        "sleep 2",
        "echo '--- Après redémarrage ---'",
        "systemctl status mon-service-demo --no-pager || true",
    ],
}


class SSMOutcome(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    SSM_REPORTED_TIMEOUT = "SSM_REPORTED_TIMEOUT"
    TARGET_NOT_MANAGED = "TARGET_NOT_MANAGED"
    ACCESS_DENIED = "ACCESS_DENIED"


@dataclasses.dataclass
class SSMExecutionResult:
    outcome: SSMOutcome
    detail: str
    raw_status: str | None = None

    @property
    def is_success(self) -> bool:
        return self.outcome is SSMOutcome.SUCCESS


class SSMExecutionError(Exception):
    pass


def _resolve_terminal_status(
    status: str | None,
    *,
    label: str,
    success_detail: str,
    cancelled_detail: str,
    timeout_detail: str,
    failure_detail: str,
) -> SSMExecutionResult:
    """Traduit un statut terminal SSM (commande ou automation) en résultat.

    Les deux flux SSM (Command et Automation) partagent le même jeu de
    statuts terminaux (Success/Cancelled/TimedOut/Failed) ; seuls les
    libellés et la source du message d'échec diffèrent selon le flux.
    """
    if status == "Success":
        return SSMExecutionResult(
            outcome=SSMOutcome.SUCCESS, detail=success_detail, raw_status=status
        )
    if status == "Cancelled":
        return SSMExecutionResult(
            outcome=SSMOutcome.CANCELLED, detail=cancelled_detail, raw_status=status
        )
    if status == "TimedOut":
        return SSMExecutionResult(
            outcome=SSMOutcome.SSM_REPORTED_TIMEOUT,
            detail=timeout_detail,
            raw_status=status,
        )
    if status == "Failed":
        return SSMExecutionResult(
            outcome=SSMOutcome.FAILED, detail=failure_detail, raw_status=status
        )
    return SSMExecutionResult(
        outcome=SSMOutcome.FAILED,
        detail=f"Statut {label} non reconnu : {status}",
        raw_status=status,
    )


def _resolve_automation_status_result(
    status: str | None, info: dict
) -> SSMExecutionResult:
    """Traduit un statut terminal d'automation SSM en résultat."""
    failure_detail = (
        info.get("FailureMessage") or "Automation SSM en échec (voir Step Executions)."
    )
    return _resolve_terminal_status(
        status,
        label="d'automation",
        success_detail="Automation exécutée avec succès.",
        cancelled_detail="Automation annulée.",
        timeout_detail="SSM a marqué l'automation comme TimedOut.",
        failure_detail=failure_detail,
    )


def _resolve_command_status_result(
    status: str | None, response: dict
) -> SSMExecutionResult:
    """Traduit un statut terminal de commande SSM en résultat."""
    failure_detail = (
        response.get("StandardErrorContent")
        or "Commande SSM en échec (voir StandardErrorContent)."
    )
    return _resolve_terminal_status(
        status,
        label="SSM",
        success_detail="Commande exécutée avec succès.",
        cancelled_detail="Commande annulée.",
        timeout_detail=(
            "SSM a marqué la commande comme TimedOut "
            "(délai d'exécution dépassé sur l'instance)."
        ),
        failure_detail=failure_detail,
    )


class SSMExecutor:
    def __init__(self, client=None):
        self._client = client or boto3.client("ssm", region_name=settings.AWS_REGION)

    def run_and_wait(
        self,
        instance_id: str | None,
        document_name: str,
        action: str | None = None,
    ) -> tuple[str, SSMExecutionResult]:
        """Point d'entrée unique du node Décision : route vers send_command
        (documents 'Command', ciblés sur une instance) ou vers
        start_automation_execution (documents 'Automation', ex.
        Custom-ScaleOutASG, qui appelle autoscaling:SetDesiredCapacity et
        n'a pas d'InstanceIds à cibler).

        Root cause du bug REMEDIATION_UNAVAILABLE observé sur ScaleOut :
        Custom-ScaleOutASG est déclaré document_type = "Automation" dans
        infra/ssm_documents.tf, or send_command() n'accepte QUE des
        documents de type "Command" — d'où l'erreur technique
        "InvalidDocument ... Only type: 'Command' is supported".
        """
        if document_name in AUTOMATION_DOCUMENTS:
            execution_id = self.start_automation(document_name)
            result = self.wait_for_automation(execution_id)
            return execution_id, result

        command_id = self.send_command(instance_id, document_name, action=action)
        result = self.wait_for_result(command_id, instance_id)
        return command_id, result

    def start_automation(
        self, document_name: str, parameters: dict | None = None
    ) -> str:
        """Lance un document SSM de type Automation. Les paramètres non
        fournis utilisent les valeurs par défaut définies dans le document
        (ex. AutoScalingGroupName / DesiredCapacity pour Custom-ScaleOutASG),
        donc `parameters` peut rester vide dans le cas nominal.

        CORRECTIF (trouvé par test de stress réel, jamais détecté par les
        tests mockés) : l'API StartAutomationExecution rejette un champ
        `Parameters` explicitement présent mais vide avec une
        ValidationException ("Member must have length greater than or
        equal to 1"). Il faut OMETTRE la clé `Parameters` de l'appel quand
        il n'y a rien à surcharger, pas envoyer un dict vide — sinon le
        document ne peut jamais utiliser ses propres valeurs par défaut,
        et ScaleOut échoue systématiquement en environnement réel.
        """
        kwargs: dict = {"DocumentName": document_name}
        if parameters:
            kwargs["Parameters"] = parameters
        try:
            response = self._client.start_automation_execution(**kwargs)
            return response["AutomationExecutionId"]
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("AccessDeniedException", "AccessDenied"):
                raise SSMExecutionError(
                    f"Accès refusé (IAM) lors du lancement de l'automation SSM : {exc}"
                ) from exc
            raise SSMExecutionError(
                f"Échec technique StartAutomationExecution : {exc}"
            ) from exc

    def wait_for_automation(self, execution_id: str) -> SSMExecutionResult:
        deadline = (
            time.monotonic()
            + settings.SSM_COMMAND_TIMEOUT_SECONDS
            + settings.SSM_POLL_GRACE_SECONDS
        )
        last_status = None

        while time.monotonic() < deadline:
            try:
                response = self._client.get_automation_execution(
                    AutomationExecutionId=execution_id
                )
            except ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code", "")
                if error_code in ("AccessDeniedException", "AccessDenied"):
                    return SSMExecutionResult(
                        outcome=SSMOutcome.ACCESS_DENIED,
                        detail=f"Accès refusé (IAM) lors du suivi de l'automation : {exc}",
                    )
                logger.exception(
                    "Erreur inattendue GetAutomationExecution('%s')",
                    execution_id,
                )
                return SSMExecutionResult(
                    outcome=SSMOutcome.FAILED,
                    detail=f"Erreur technique lors du suivi de l'automation SSM : {exc}",
                )

            info = response["AutomationExecution"]
            status = info.get("AutomationExecutionStatus")
            last_status = status

            if status in _AUTOMATION_PENDING_STATUSES:
                time.sleep(settings.SSM_POLL_INTERVAL_SECONDS)
                continue

            result = _resolve_automation_status_result(status, info)
            if result is not None:
                return result

        return SSMExecutionResult(
            outcome=SSMOutcome.TIMED_OUT,
            detail=(
                f"Aucun statut terminal reçu après {settings.SSM_COMMAND_TIMEOUT_SECONDS}s "
                f"(dernier statut observé : {last_status})."
            ),
            raw_status=last_status,
        )

    def send_command(
        self, instance_id: str, document_name: str, action: str | None = None
    ) -> str:
        """Envoie la commande SSM, avec les paramètres shell réels associés
        à l'action métier (US 3.1) si le document est AWS-RunShellScript."""
        if not self._is_instance_managed(instance_id):
            raise SSMExecutionError(
                f"Instance '{instance_id}' non gérée par SSM Agent (hors ligne ou non enregistrée)."
            )

        send_kwargs = {
            "InstanceIds": [instance_id],
            "DocumentName": document_name,
            "TimeoutSeconds": settings.SSM_COMMAND_TIMEOUT_SECONDS,
        }

        if document_name == "AWS-RunShellScript":
            commands = ACTION_TO_SHELL_COMMANDS.get(action or "")
            if not commands:
                raise SSMExecutionError(
                    f"Aucune commande shell définie pour l'action '{action}' "
                    f"(ACTION_TO_SHELL_COMMANDS) — refus d'envoyer une commande vide."
                )
            send_kwargs["Parameters"] = {"commands": commands}

        try:
            response = self._client.send_command(**send_kwargs)
            return response["Command"]["CommandId"]
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("AccessDeniedException", "AccessDenied"):
                raise SSMExecutionError(
                    f"Accès refusé (IAM) lors de l'envoi de la commande SSM : {exc}"
                ) from exc
            raise SSMExecutionError(f"Échec technique SendCommand : {exc}") from exc

    def _is_instance_managed(self, instance_id: str) -> bool:
        try:
            response = self._client.describe_instance_information(
                Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]
            )
            infos = response.get("InstanceInformationList", [])
            return bool(infos) and infos[0].get("PingStatus") == "Online"
        except ClientError as exc:
            logger.warning(
                "Impossible de vérifier l'état SSM Agent de '%s' (on tente quand même l'envoi) : %s",
                instance_id,
                exc,
            )
            return True

    def wait_for_result(self, command_id: str, instance_id: str) -> SSMExecutionResult:
        deadline = (
            time.monotonic()
            + settings.SSM_COMMAND_TIMEOUT_SECONDS
            + settings.SSM_POLL_GRACE_SECONDS
        )
        last_status = None

        while time.monotonic() < deadline:
            try:
                response = self._client.get_command_invocation(
                    CommandId=command_id, InstanceId=instance_id
                )
            except ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code", "")
                if error_code == "InvocationDoesNotExist":
                    time.sleep(settings.SSM_POLL_INTERVAL_SECONDS)
                    continue
                if error_code in ("AccessDeniedException", "AccessDenied"):
                    return SSMExecutionResult(
                        outcome=SSMOutcome.ACCESS_DENIED,
                        detail=f"Accès refusé (IAM) lors du suivi de la commande : {exc}",
                    )
                logger.exception(
                    "Erreur inattendue GetCommandInvocation('%s')",
                    command_id,
                )
                return SSMExecutionResult(
                    outcome=SSMOutcome.FAILED,
                    detail=f"Erreur technique lors du suivi de la commande SSM : {exc}",
                )

            status = response.get("Status")
            last_status = status

            if status in _PENDING_STATUSES:
                time.sleep(settings.SSM_POLL_INTERVAL_SECONDS)
                continue

            result = _resolve_command_status_result(status, response)
            if result is not None:
                return result

        return SSMExecutionResult(
            outcome=SSMOutcome.TIMED_OUT,
            detail=f"Aucun statut terminal reçu après {settings.SSM_COMMAND_TIMEOUT_SECONDS}s (dernier statut observé : {last_status}).",
            raw_status=last_status,
        )
