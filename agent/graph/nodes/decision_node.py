from __future__ import annotations

import logging
import time
from decimal import Decimal

from langgraph.types import interrupt

from agent.config import settings
from agent.dynamo_logger import DynamoDecisionLogger
from agent.graph.freshness import FreshnessVerdict, check_still_relevant
from agent.graph.whitelist import get_ssm_document, is_allowed
from agent.idempotency_lock import ActionIdempotencyLock, LockOutcome
from agent.models import (
    AlarmPayload,
    DecisionResult,
    DecisionStatus,
    HumanValidation,
    RCAResult,
)
from agent.ssm_executor import SSMExecutionError, SSMExecutor, SSMOutcome

logger = logging.getLogger(__name__)

NODE_NAME = "Decision"

_OUTCOME_TO_STATUS = {
    SSMOutcome.SUCCESS: DecisionStatus.EXECUTED,
    SSMOutcome.FAILED: DecisionStatus.EXECUTION_FAILED,
    SSMOutcome.CANCELLED: DecisionStatus.EXECUTION_FAILED,
    SSMOutcome.SSM_REPORTED_TIMEOUT: DecisionStatus.EXECUTION_TIMED_OUT,
    SSMOutcome.TIMED_OUT: DecisionStatus.EXECUTION_TIMED_OUT,
    SSMOutcome.TARGET_NOT_MANAGED: DecisionStatus.REMEDIATION_UNAVAILABLE,
    SSMOutcome.ACCESS_DENIED: DecisionStatus.REMEDIATION_UNAVAILABLE,
}

RISKY_ACTIONS = {"RollbackDeployment", "RestartService"}

_ssm_executor = SSMExecutor()
_idempotency_lock = ActionIdempotencyLock(table_name=settings.ACTION_LOCKS_TABLE)
_decision_logger = logging.getLogger("agent.decisions")
_decision_dynamo_logger = DynamoDecisionLogger()


def _rehydrate_state(state) -> None:
    if isinstance(state.rca, dict):
        state.rca = RCAResult(**state.rca)
    if isinstance(state.alarm, dict):
        state.alarm = AlarmPayload(**state.alarm)


def _requires_human_validation(action: str, confidence: int) -> bool:
    if confidence < settings.CONFIDENCE_THRESHOLD:
        return True
    return action in RISKY_ACTIONS


def _build_validation_payload(state, alarm, rca, action: str) -> dict:
    return {
        "incident_id": state.incident_id,
        "alarm_name": alarm.alarm_name,
        "alarm_type": alarm.alarm_type,
        "instance_id": alarm.instance_id,
        "proposed_action": action,
        "diagnosis": rca.diagnosis,
        "confidence": rca.confidence,
        "judge_verdict": rca.judge_verdict,
        "reason": "Action à risque ou confiance insuffisante : validation requise avant exécution.",
    }


def decision_node(payload: dict):
    state = payload["state"]

    _rehydrate_state(state)

    alarm = state.alarm
    rca = state.rca
    action = rca.suggested_action

    if action == "NONE":
        raise ValueError(
            "Invariant violé : suggested_action='NONE' n'aurait jamais dû "
            "atteindre le node Décision (RCAResult ne l'accepte plus)."
        )

    human_validation: HumanValidation | None = None

    if _requires_human_validation(action, rca.confidence):
        human_response = interrupt(_build_validation_payload(state, alarm, rca, action))
        human_validation = HumanValidation(
            approved=human_response.get("approved", False),
            validator=human_response.get("validator", "unknown"),
            validated_at=human_response.get("validated_at"),
            reason=human_response.get("reason"),
        )

    return _finalize_decision(state, alarm, action, human_validation)


def _handle_human_rejection(
    state, action: str, human_validation: HumanValidation
) -> dict:
    is_timeout = human_validation.validator == "system_timeout"
    state.decision = DecisionResult(
        status=(
            DecisionStatus.VALIDATION_TIMEOUT_ACTION_CANCELLED
            if is_timeout
            else DecisionStatus.REJECTED_BY_HUMAN
        ),
        action=action,
        detail=human_validation.reason or "Rejeté par validation humaine.",
        human_validator=human_validation.validator,
        human_validated_at=human_validation.validated_at,
    )
    _log_decision(state)
    state.add_trace("decision", f"Décision rejetée ({human_validation.validator})")
    return {"state": state}


def _handle_stale_freshness(
    state, alarm, action: str, human_validation: HumanValidation
) -> dict | None:
    """Revérifie la fraîcheur de l'alarme après une reprise post-validation
    humaine. Retourne un résultat terminal si la situation a changé entre
    temps (résolue ou aggravée), sinon None pour poursuivre le flux normal."""
    freshness = check_still_relevant(alarm, action)
    state.add_trace(
        "decision",
        f"Fraîcheur revérifiée à la reprise : {freshness.verdict.value} "
        f"(état alarme actuel = {freshness.current_alarm_state})",
    )

    if freshness.verdict == FreshnessVerdict.ALARM_RESOLVED:
        state.decision = DecisionResult(
            status=DecisionStatus.VALIDATION_STALE_ACTION_SKIPPED,
            action=action,
            detail=freshness.detail,
            human_validator=human_validation.validator,
            human_validated_at=human_validation.validated_at,
        )
        _log_decision(state)
        state.add_trace(
            "decision",
            "Action non exécutée : situation résolue pendant l'attente de validation",
        )
        return {"state": state}

    if freshness.verdict == FreshnessVerdict.ALARM_WORSENED:
        state.decision = DecisionResult(
            status=DecisionStatus.VALIDATION_STALE_RECONFIRMATION_REQUIRED,
            action=action,
            detail=freshness.detail,
            human_validator=human_validation.validator,
            human_validated_at=human_validation.validated_at,
        )
        _log_decision(state)
        state.add_trace(
            "decision",
            "Clôture non confirmée : situation dégradée depuis le diagnostic, re-triage requis",
        )
        return {"state": state}

    return None


def _handle_missing_instance_id(state, alarm, action: str, human_validation) -> dict:
    logger.error(
        "instance_id manquant pour l'alarme. Contenu complet de alarm : %s",
        alarm.model_dump() if hasattr(alarm, "model_dump") else alarm,
    )
    reason = (
        f"Aucun instance_id résolu pour l'alarme '{alarm.alarm_name}' "
        f"(type={alarm.alarm_type}). Action '{action}' impossible à cibler. "
        "Vérifiez que l'alarme inclut bien une dimension InstanceId dans Trigger.Dimensions."
    )
    state.decision = DecisionResult(
        status=DecisionStatus.REMEDIATION_UNAVAILABLE,
        action=action,
        detail=reason,
        refusal_reason=reason,
        human_validator=(human_validation.validator if human_validation else None),
        human_validated_at=(
            human_validation.validated_at if human_validation else None
        ),
    )
    _log_decision(state)
    state.add_trace(
        "decision",
        "Action refusée : instance_id manquant (target resolution failure)",
    )
    return {"state": state}


def _execute_remediation(state, alarm, action: str, human_validation) -> dict:
    """Acquiert le verrou d'idempotence puis exécute (ou refuse d'exécuter)
    l'action corrective via SSM."""
    lock_result = _idempotency_lock.try_acquire_detailed(
        resource_id=alarm.instance_id,
        action_type=action,
        incident_id=state.incident_id,
    )
    if lock_result.outcome is LockOutcome.ALREADY_HELD:
        state.decision = DecisionResult(
            status=DecisionStatus.DUPLICATE_ACTION_SKIPPED,
            action=action,
            detail=lock_result.detail,
        )
        _log_decision(state)
        state.add_trace("decision", "Action ignorée : verrou d'idempotence déjà pris")
        return {"state": state}
    if lock_result.outcome is LockOutcome.ACQUISITION_FAILED:
        state.decision = DecisionResult(
            status=DecisionStatus.LOCK_ACQUISITION_FAILED,
            action=action,
            detail=lock_result.detail,
            refusal_reason=lock_result.detail,
        )
        _log_decision(state)
        state.add_trace(
            "decision",
            "Action non exécutée : panne technique du verrou d'idempotence",
        )
        return {"state": state}

    try:
        document = get_ssm_document(action)
        t_start = time.monotonic()

        command_id, result = _ssm_executor.run_and_wait(
            alarm.instance_id, document, action=action
        )
    except SSMExecutionError as exc:
        _idempotency_lock.release(resource_id=alarm.instance_id, action_type=action)
        reason = f"Remédiation indisponible : {exc}"
        state.decision = DecisionResult(
            status=DecisionStatus.REMEDIATION_UNAVAILABLE,
            action=action,
            detail=reason,
            refusal_reason=reason,
        )
        _log_decision(state)
        state.add_trace("decision", f"Envoi SSM impossible : {exc}")
        return {"state": state}

    resolution_time_seconds = round(time.monotonic() - t_start, 2)
    status = _OUTCOME_TO_STATUS[result.outcome]

    if status != DecisionStatus.EXECUTED:
        _idempotency_lock.release(resource_id=alarm.instance_id, action_type=action)

    state.decision = DecisionResult(
        status=status,
        action=action,
        ssm_command_id=command_id,
        detail=result.detail,
        resolution_time_seconds=resolution_time_seconds,
        refusal_reason=(result.detail if status != DecisionStatus.EXECUTED else None),
        human_validator=(human_validation.validator if human_validation else None),
        human_validated_at=(
            human_validation.validated_at if human_validation else None
        ),
    )
    _log_decision(state)
    state.add_trace("decision", f"SSM {document} -> {status.value}")
    return {"state": state}


def _finalize_decision(
    state, alarm, action: str, human_validation: HumanValidation | None
) -> dict:
    if human_validation is not None:
        if not human_validation.approved:
            return _handle_human_rejection(state, action, human_validation)

        stale_result = _handle_stale_freshness(state, alarm, action, human_validation)
        if stale_result is not None:
            return stale_result

    if not is_allowed(alarm.alarm_type, action):
        reason = f"Action '{action}' non autorisée pour le type d'alarme '{alarm.alarm_type}'"
        state.decision = DecisionResult(
            status=DecisionStatus.REFUSED_BY_WHITELIST,
            action=action,
            detail=reason,
            refusal_reason=reason,
            human_validator=(human_validation.validator if human_validation else None),
            human_validated_at=(
                human_validation.validated_at if human_validation else None
            ),
        )
        _log_decision(state)
        state.add_trace("decision", f"Action refusée par whitelist : {action}")
        return {"state": state}

    if not alarm.instance_id:
        return _handle_missing_instance_id(state, alarm, action, human_validation)

    return _execute_remediation(state, alarm, action, human_validation)


def _to_decimal_or_none(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    return value


def _log_decision(state) -> None:
    try:
        _decision_logger.info(
            "decision",
            extra={
                "incident_id": state.incident_id,
                "status": state.decision.status.value,
                "action": state.decision.action,
            },
        )
    except Exception:
        logger.exception("Échec de l'écriture du log de décision (best-effort, ignoré)")

    try:
        _decision_dynamo_logger.log_node_contribution(
            incident_id=state.incident_id,
            node_name=NODE_NAME,
            confidence=getattr(state.rca, "confidence", None),
            extra={
                "decision_status": state.decision.status.value,
                "action": state.decision.action,
                "ssm_command_id": state.decision.ssm_command_id,
                # DynamoDB n'accepte pas les float natifs : conversion en Decimal
                "resolution_time_seconds": _to_decimal_or_none(
                    state.decision.resolution_time_seconds
                ),
                "refusal_reason": state.decision.refusal_reason,
                "human_validator": state.decision.human_validator,
                "human_validated_at": state.decision.human_validated_at,
            },
        )
    except Exception:
        logger.exception(
            "Échec de l'écriture DynamoDB de la décision (best-effort, ignoré) — "
            "incident_id=%s, status=%s",
            state.incident_id,
            state.decision.status.value,
        )