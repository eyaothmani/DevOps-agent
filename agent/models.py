from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_incident_id() -> str:
    return f"inc-{uuid4().hex[:12]}"


class JudgeVerdict(str, Enum):
    COHERENT = "coherent"
    INCOHERENT = "incoherent"
    INCERTAIN = "incertain"


class JudgeResult(BaseModel):
    """Sortie du node Judge — second avis indépendant sur le diagnostic."""

    verdict: JudgeVerdict = JudgeVerdict.INCERTAIN
    justification: str = ""


class AlarmState(str, Enum):
    ALARM = "ALARM"
    OK = "OK"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class AlarmPayload(BaseModel):
    """Résultat du parsing d'un message SNS émis par une alarme CloudWatch (US 2.2)."""

    incident_id: str = Field(default_factory=_new_incident_id)
    alarm_name: str
    alarm_type: str  # ex: "CPUHigh", "ServiceDown", "HighErrorRate"
    new_state: AlarmState
    reason: str | None = None
    region: str | None = None
    instance_id: str | None = None
    metric_name: str | None = None
    namespace: str | None = None
    threshold: float | None = None
    timestamp: str = Field(default_factory=_utcnow_iso)
    raw_message: dict[str, Any] = Field(default_factory=dict)

    @field_validator("alarm_type")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("alarm_type ne peut pas être vide")
        return v


class LogEvent(BaseModel):
    timestamp: str
    message: str
    log_stream: str | None = None


# Alias tolérés pour suggested_action : Bedrock renvoie parfois l'action
# dans un format proche mais non conforme au Literal attendu (SCALE_OUT,
# scale-out, etc.). On normalise plutôt que de consommer une tentative
# de retry pour un simple problème de casse/format.
#
# Volontairement, aucun alias ne pointe vers "NONE" (none, no_action,
# noaction, aucune_action) : "NONE" n'est pas une action acceptée par le
# système. Toute variante de "pas d'action" tombe donc dans le Literal
# invalide ci-dessous, ce qui déclenche le retry Pydantic existant (US 4.2)
# au lieu d'être normalisée silencieusement.
_ACTION_ALIASES = {
    "restartservice": "RestartService",
    "restart_service": "RestartService",
    "restart-service": "RestartService",
    "scaleout": "ScaleOut",
    "scale_out": "ScaleOut",
    "scale-out": "ScaleOut",
    "rollbackdeployment": "RollbackDeployment",
    "rollback_deployment": "RollbackDeployment",
    "rollback-deployment": "RollbackDeployment",
}


class RCAResult(BaseModel):
    """Sortie structurée de l'analyse Bedrock — schéma validé (US 4.2).

    "NONE" n'apparaît pas dans le Literal ci-dessous et le champ n'a pas de
    valeur par défaut : il est obligatoire, et toute valeur qui ne matche pas
    exactement une des trois actions réelles échoue à la validation Pydantic
    — y compris "NONE" — ce qui déclenche automatiquement le mécanisme de
    retry existant dans BedrockClient.diagnose(), quel que soit l'état de
    l'alarme (ALARM ou OK). C'est la source unique de vérité : cette règle
    n'a pas besoin d'être dupliquée dans le prompt, dans bedrock_client.py
    ou dans decision_node.py.
    """

    diagnosis: str
    confidence: int = Field(ge=0, le=100)
    reasoning_steps: list[str] = Field(default_factory=list)
    suggested_action: Literal["RestartService", "ScaleOut", "RollbackDeployment"]
    model_id: str | None = None
    tokens_used: int = 0
    raw_response: str | None = None
    groundedness_score: float | None = None
    judge_verdict: str | None = None
    # ↑ US 4.9 — renseigné après coup par judge_node.py. Pydantic v2 interdit
    # l'assignation d'un attribut non déclaré (`ValueError`), le champ doit
    # donc exister ici même s'il n'est jamais fourni à la création.

    @field_validator("suggested_action", mode="before")
    @classmethod
    def _normalize_suggested_action(cls, v: Any) -> Any:
        """
        Normalise les variations de casse/format avant la validation stricte
        du Literal (ex: "SCALE_OUT" -> "ScaleOut"). Si aucune correspondance
        n'est trouvée (ex: une phrase libre, ou "NONE" sous quelque forme
        que ce soit), la valeur brute est renvoyée telle quelle afin que la
        validation Pydantic échoue normalement et déclenche le retry
        existant (US 4.2) — ce cas-là n'est pas un problème de format mais
        un vrai défaut de diagnostic actionnable.
        """
        if not isinstance(v, str):
            return v
        key = v.strip().lower().replace(" ", "_").replace("-", "_")
        return _ACTION_ALIASES.get(key, v)

    @field_validator("reasoning_steps", mode="before")
    @classmethod
    def _coerce_reasoning_steps(cls, v: Any) -> Any:
        """
        Bedrock renvoie parfois reasoning_steps comme une liste d'objets
        (ex: {"evidence_quote": "...", "source": "..."}) au lieu d'une liste
        de strings simples. On normalise ici plutôt que de faire échouer
        toute la validation et de forcer un retry inutile.
        """
        if not isinstance(v, list):
            return v

        normalized: list[str] = []
        for step in v:
            if isinstance(step, str):
                text = step
            elif isinstance(step, dict):
                # Ordre de préférence des clés connues renvoyées par Bedrock
                text = (
                    step.get("evidence_quote")
                    or step.get("reasoning")
                    or step.get("text")
                    or step.get("detail")
                )
                if not text:
                    # Dernier recours : concatène les valeurs texte du dict
                    text = " — ".join(
                        str(val) for val in step.values() if isinstance(val, str)
                    ) or str(step)
            else:
                text = str(step)

            text = text.strip()
            if text:
                normalized.append(text)

        return normalized


class DecisionStatus(str, Enum):
    EXECUTED = "EXECUTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"

    REFUSED_BY_WHITELIST = "REFUSED_BY_WHITELIST"
    SKIPPED_KILL_SWITCH = "SKIPPED_KILL_SWITCH"
    SKIPPED_COOLDOWN = "SKIPPED_COOLDOWN"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    LOW_CONFIDENCE_SKIPPED = "LOW_CONFIDENCE_SKIPPED"
    EXECUTION_TIMED_OUT = "EXECUTION_TIMED_OUT"
    REMEDIATION_UNAVAILABLE = "REMEDIATION_UNAVAILABLE"
    DUPLICATE_ACTION_SKIPPED = "DUPLICATE_ACTION_SKIPPED"
    # Distinct de DUPLICATE_ACTION_SKIPPED : ici le verrou n'a pas pu être
    # évalué du tout (panne/throttling DynamoDB), ce n'est PAS un doublon
    # légitime. Fusionner les deux sous un même statut masquerait un
    # incident d'infrastructure derrière un message anodin.
    LOCK_ACQUISITION_FAILED = "LOCK_ACQUISITION_FAILED"

    # NOTE : NO_ACTION_NEEDED / NO_ACTION_CONFIRMED_BY_HUMAN sont conservés
    # dans l'enum pour compatibilité avec l'historique DynamoDB existant
    # (ne pas casser la lecture d'anciens incidents), mais ne sont plus
    # atteignables par un nouveau diagnostic puisque RCAResult.suggested_action
    # ne peut plus valoir "NONE".
    NO_ACTION_NEEDED = "NO_ACTION_NEEDED"
    NO_ACTION_CONFIRMED_BY_HUMAN = "NO_ACTION_CONFIRMED_BY_HUMAN"

    # --- US 4.8 : Human-in-the-loop natif (interrupt LangGraph) ---
    AWAITING_HUMAN_VALIDATION = "AWAITING_HUMAN_VALIDATION"
    REJECTED_BY_HUMAN = "REJECTED_BY_HUMAN"
    VALIDATION_STALE_ACTION_SKIPPED = "VALIDATION_STALE_ACTION_SKIPPED"
    VALIDATION_STALE_RECONFIRMATION_REQUIRED = (
        "VALIDATION_STALE_RECONFIRMATION_REQUIRED"
    )
    VALIDATION_TIMEOUT_ACTION_CANCELLED = "VALIDATION_TIMEOUT_ACTION_CANCELLED"


class HumanValidation(BaseModel):
    """US 4.8 — Réponse humaine (ou système, en cas de timeout) reçue via
    Command(resume=...) après un interrupt() du node Décision."""

    approved: bool = False
    validator: str = "unknown"
    validated_at: str | None = None
    reason: str | None = None


class DecisionResult(BaseModel):
    status: DecisionStatus = DecisionStatus.NOT_IMPLEMENTED
    action: str | None = None
    ssm_command_id: str | None = None
    resolution_time_seconds: float | None = None
    refusal_reason: str | None = None
    detail: str | None = None
    # US 4.8 — traçabilité de la validation humaine (audit trail).
    human_validator: str | None = None
    human_validated_at: str | None = None


class CommunicationStatus(str, Enum):
    SENT = "SENT"
    FAILED = "FAILED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class CommunicationResult(BaseModel):
    status: CommunicationStatus = CommunicationStatus.NOT_IMPLEMENTED
    message_preview: str | None = None
    channel: str | None = None


class GraphState(BaseModel):
    incident_id: str
    alarm: AlarmPayload
    logs: list[LogEvent] = Field(default_factory=list)
    rca: RCAResult | None = None
    decision: DecisionResult | None = None
    communication: CommunicationResult | None = None

    # Traçabilité d'exécution du graphe (utile pour debug + soutenance)
    trace: list[str] = Field(default_factory=list)

    def add_trace(self, node_name: str, note: str = "") -> None:
        entry = f"[{_utcnow_iso()}] {node_name}" + (f" — {note}" if note else "")
        self.trace.append(entry)

    model_config = {"arbitrary_types_allowed": True}
