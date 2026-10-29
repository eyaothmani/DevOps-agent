from __future__ import annotations

import logging

from agent.bedrock_client import BedrockClient
from agent.config import settings
from agent.dynamo_logger import DynamoDecisionLogger
from agent.graph.state import AgentState
from agent.log_fetcher import format_logs_for_prompt
from agent.models import JudgeVerdict

logger = logging.getLogger(__name__)
NODE_NAME = "Judge"

_bedrock_client = BedrockClient()
_decision_logger = DynamoDecisionLogger()


def judge_node(agent_state: AgentState) -> dict:
    state = agent_state["state"]
    rca = state.rca

    if rca is None:
        return {"state": state}

    logs_text = format_logs_for_prompt(state.logs)
    alarm = state.alarm
    alarm_context_text = (
        f"{alarm.alarm_name} {alarm.reason or ''} {alarm.metric_name or ''} "
        f"{alarm.threshold if alarm.threshold is not None else ''}"
    )
    verdict_result = _bedrock_client.judge(
        logs_text=logs_text,
        diagnosis=rca.diagnosis,
        alarm_context=alarm_context_text,
    )

    rca.judge_verdict = verdict_result.verdict.value

    state.add_trace(NODE_NAME, f"verdict={verdict_result.verdict.value}")

    _decision_logger.log_node_contribution(
        incident_id=state.incident_id,
        node_name=NODE_NAME,
        extra={
            "judge_verdict": verdict_result.verdict.value,
            "judge_justification": verdict_result.justification,
        },
    )

    if (
        verdict_result.verdict == JudgeVerdict.INCOHERENT
        and rca.confidence >= settings.CONFIDENCE_THRESHOLD
    ):
        original_confidence = rca.confidence
        rca.confidence = settings.CONFIDENCE_THRESHOLD - 1
        state.add_trace(
            NODE_NAME,
            f"confiance forcée de {original_confidence} à {rca.confidence} (désaccord juge)",
        )
        logger.warning(
            "[%s] Désaccord juge/diagnostic pour incident_id=%s — confiance rabaissée sous le seuil",
            NODE_NAME,
            state.incident_id,
        )

    return {"state": state}
