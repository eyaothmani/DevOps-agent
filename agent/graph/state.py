from __future__ import annotations

from typing import TypedDict

from agent.models import GraphState


class AgentState(TypedDict):
    state: GraphState
