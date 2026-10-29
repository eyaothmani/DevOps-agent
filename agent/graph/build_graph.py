"""
build_graph.py
----------------
US 2.1 — Squelette LangGraph multi-agents (StateGraph).

Construit le graphe à 4 nodes (Diagnostic -> Judge -> Décision -> Communication)
avec un état partagé, et l'exécute de bout en bout.

Le graphe est exportable en Mermaid pour la documentation/soutenance
"""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph
from langgraph_checkpoint_aws import DynamoDBSaver

from agent.config import settings
from agent.graph.nodes.communication_node import communication_node
from agent.graph.nodes.decision_node import decision_node
from agent.graph.nodes.diagnostic_node import diagnostic_node
from agent.graph.nodes.judge_node import judge_node
from agent.graph.nodes.kill_switch_node import kill_switch_node, route_after_kill_switch
from agent.graph.state import AgentState
from agent.models import AlarmPayload, GraphState

logger = logging.getLogger(__name__)

# US 4.8 — Checkpointer persistant (DynamoDB), requis par interrupt().
# Sans lui, l'état suspendu par decision_node.interrupt() ne survivrait pas
# entre l'invocation Lambda initiale (déclenchée par SNS) et l'invocation
# de reprise (déclenchée par le clic sur le bouton Slack), qui tournent
# dans des processus/conteneurs distincts. Instancié une seule fois au
# niveau module pour être réutilisé entre invocations Lambda "chaudes".
_checkpointer = DynamoDBSaver(
    table_name=settings.CHECKPOINTS_TABLE,
    region_name=settings.AWS_REGION,
)


def build_agent_graph():
    """Construit le graphe LangGraph complet avec les 4 nœuds métier."""
    graph = StateGraph(AgentState)

    # 1. Ajout des nœuds
    graph.add_node("kill_switch", kill_switch_node)
    graph.add_node("diagnostic", diagnostic_node)
    graph.add_node("judge", judge_node)
    graph.add_node("decision", decision_node)
    graph.add_node("communication", communication_node)

    # 2. Chaînage des transitions
    graph.add_edge(START, "kill_switch")

    # US 4.3 — routage conditionnel réel : si le kill switch est engagé,
    # on saute directement à Communication (pour notifier l'équipe que
    # l'incident a été ignoré) sans jamais appeler Bedrock ni SSM. C'est ce
    # add_conditional_edges qui interrompt effectivement le graphe — un
    # simple add_edge inconditionnel ne suffit pas, quel que soit le statut
    # posé sur l'état par kill_switch_node.
    graph.add_conditional_edges(
        "kill_switch",
        route_after_kill_switch,
        {"continue": "diagnostic", "stop": "communication"},
    )
    graph.add_edge("diagnostic", "judge")
    graph.add_edge("judge", "decision")
    graph.add_edge("decision", "communication")
    graph.add_edge("communication", END)

    return graph.compile(checkpointer=_checkpointer)


def export_mermaid_diagram() -> str:
    """Retourne la représentation Mermaid du graphe compilé (US 2.1 —
    'exportable/visualisable pour la documentation et la soutenance')."""
    compiled = build_agent_graph()
    try:
        return compiled.get_graph().draw_mermaid()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Export Mermaid natif indisponible (%s), repli statique.", exc)
        return (
            "graph TD\n"
            "    START([START]) --> KillSwitch\n"
            "    KillSwitch -- continue --> Diagnostic\n"
            "    KillSwitch -- stop (kill switch engage) --> Communication\n"
            "    Diagnostic --> Judge\n"
            "    Judge --> Decision\n"
            "    Decision --> Communication\n"
            "    Communication --> END([END])\n"
        )


# Singleton importé par lambda_handler.py, resume_handler.py et
# timeout_checker.py — garantit que les 3 Lambdas utilisent EXACTEMENT le
# même graphe compilé (même checkpointer) plutôt que 3 instances
# indépendantes non synchronisées.
graph = build_agent_graph()


def run_graph_for_alarm(alarm: AlarmPayload) -> GraphState:
    """Point d'entrée utilitaire (tests locaux / démo) : construit l'état
    initial à partir d'une alarme déjà parsée et exécute le graphe complet.

    ATTENTION : un checkpointer étant configuré, un `thread_id` est requis
    dans la config. Si l'incident déclenche une validation humaine (US 4.8),
    cette fonction s'arrête à l'interruption — utiliser
    `agent.graph_invocation.invoke_graph_with_interrupt_handling` pour le
    flux Lambda complet (notification Slack + reprise)."""
    initial_state = GraphState(incident_id=alarm.incident_id, alarm=alarm)
    initial_state.add_trace("GraphInit", "état initial créé")

    config = {"configurable": {"thread_id": alarm.incident_id}}
    result: AgentState = graph.invoke({"state": initial_state}, config=config)
    if "__interrupt__" in result:
        logger.warning(
            "run_graph_for_alarm : graphe interrompu (validation humaine requise) "
            "pour incident_id=%s — utiliser invoke_graph_with_interrupt_handling "
            "pour gérer ce cas en production.",
            alarm.incident_id,
        )
        return initial_state
    return result["state"]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=== Diagramme Mermaid du graphe ===")
    print(export_mermaid_diagram())
