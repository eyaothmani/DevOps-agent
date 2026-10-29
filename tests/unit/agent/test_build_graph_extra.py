"""
Tests unitaires — agent/graph/build_graph.py

Couvre les branches non testées jusqu'ici :
  * export_mermaid_diagram() : chemin nominal (export natif LangGraph) et
    repli statique quand l'export natif échoue.
  * run_graph_for_alarm() : complétion normale, et cas où le graphe est
    interrompu (validation humaine requise) — la fonction doit alors
    renvoyer l'état initial plutôt que planter.

Le graphe compilé réel (checkpointer DynamoDB) n'est jamais invoqué ici :
build_agent_graph et le singleton `graph` sont mockés.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import agent.graph.build_graph as bg
from agent.models import AlarmPayload, AlarmState


def _make_alarm(alarm_type="ServiceDown", instance_id="i-0123456789abcdef0"):
    return AlarmPayload(
        alarm_name=f"{alarm_type}-test",
        alarm_type=alarm_type,
        new_state=AlarmState.ALARM,
        instance_id=instance_id,
    )


class TestExportMermaidDiagram:
    def test_native_export_success_returns_native_diagram(self, monkeypatch):
        fake_graph_repr = MagicMock()
        fake_graph_repr.draw_mermaid.return_value = "graph TD\n  A-->B\n"
        fake_compiled = MagicMock()
        fake_compiled.get_graph.return_value = fake_graph_repr

        monkeypatch.setattr(bg, "build_agent_graph", lambda: fake_compiled)

        result = bg.export_mermaid_diagram()

        assert result == "graph TD\n  A-->B\n"
        fake_compiled.get_graph.assert_called_once()
        fake_graph_repr.draw_mermaid.assert_called_once()

    def test_native_export_failure_falls_back_to_static_diagram(self, monkeypatch):
        fake_compiled = MagicMock()
        fake_compiled.get_graph.side_effect = RuntimeError("draw_mermaid indisponible")

        monkeypatch.setattr(bg, "build_agent_graph", lambda: fake_compiled)

        result = bg.export_mermaid_diagram()

        # Repli statique : on vérifie la structure attendue du graphe, pas
        # le texte exact (fragile), pour rester robuste à un reformattage.
        assert "KillSwitch" in result
        assert "Diagnostic" in result
        assert "Judge" in result
        assert "Decision" in result
        assert "Communication" in result
        assert "END" in result

    def test_native_export_failure_is_logged_as_warning(self, monkeypatch, caplog):
        fake_compiled = MagicMock()
        fake_compiled.get_graph.side_effect = RuntimeError("boom")
        monkeypatch.setattr(bg, "build_agent_graph", lambda: fake_compiled)

        with caplog.at_level("WARNING", logger="agent.graph.build_graph"):
            bg.export_mermaid_diagram()

        assert "repli statique" in caplog.text


class TestRunGraphForAlarm:
    def test_normal_completion_returns_final_state(self, monkeypatch):
        alarm = _make_alarm()
        final_state = MagicMock(name="final_state")
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {"state": final_state}
        monkeypatch.setattr(bg, "graph", mock_graph)

        result = bg.run_graph_for_alarm(alarm)

        assert result is final_state
        mock_graph.invoke.assert_called_once()
        _, kwargs = mock_graph.invoke.call_args
        assert kwargs["config"]["configurable"]["thread_id"] == alarm.incident_id

    def test_interrupted_graph_returns_initial_state(self, monkeypatch):
        alarm = _make_alarm()
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {"__interrupt__": [MagicMock()]}
        monkeypatch.setattr(bg, "graph", mock_graph)

        result = bg.run_graph_for_alarm(alarm)

        # Pas d'état final disponible : la fonction renvoie l'état initial
        # qu'elle vient de construire ; à charge de l'appelant d'utiliser
        # invoke_graph_with_interrupt_handling pour le flux complet.
        assert result.incident_id == alarm.incident_id
        assert result.alarm is alarm

    def test_interrupted_graph_logs_warning(self, monkeypatch, caplog):
        alarm = _make_alarm()
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {"__interrupt__": [MagicMock()]}
        monkeypatch.setattr(bg, "graph", mock_graph)

        with caplog.at_level("WARNING", logger="agent.graph.build_graph"):
            bg.run_graph_for_alarm(alarm)

        assert "graphe interrompu" in caplog.text
