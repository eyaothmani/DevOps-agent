from __future__ import annotations

import logging

from agent.dynamo_logger import DynamoDecisionLogger
from agent.graph.state import AgentState
from agent.kill_switch import KillSwitch
from agent.models import DecisionResult, DecisionStatus

logger = logging.getLogger(__name__)
NODE_NAME = "KillSwitch"

_decision_logger = DynamoDecisionLogger()

_kill_switch = KillSwitch()


def kill_switch_node(agent_state: dict) -> dict:
    state = agent_state["state"]
    if not _kill_switch.is_agent_enabled():
        state.decision = DecisionResult(status=DecisionStatus.SKIPPED_KILL_SWITCH)
        state.add_trace("kill_switch", "Agent désactivé par kill switch")
        return {"state": state}
    return {"state": state}


def route_after_kill_switch(agent_state: AgentState) -> str:
    state = agent_state["state"]

    if (
        state.decision is not None
        and state.decision.status == DecisionStatus.SKIPPED_KILL_SWITCH
    ):
        return "stop"

    return "continue"
