"""
Tests unitaires — agent/graph/whitelist.py

Ce module est le garde-fou qui décide quelles actions correctives sont
autorisées pour quel type d'alarme. Couverture ciblée à 100% : c'est un
petit fichier sans dépendance externe, et une régression ici pourrait
laisser passer une action non autorisée.
"""

from __future__ import annotations

from agent.graph.whitelist import (
    ACTION_TO_SSM_DOCUMENT,
    ALLOWED_ACTIONS_BY_ALARM_TYPE,
    get_ssm_document,
    is_allowed,
)


class TestIsAllowed:
    def test_allowed_pair_returns_true(self):
        assert is_allowed("CPUHigh", "ScaleOut") is True

    def test_action_not_matching_alarm_type_returns_false(self):
        # RestartService existe bien dans ACTION_TO_SSM_DOCUMENT mais n'est
        # pas whitelisté pour CPUHigh (seul ScaleOut l'est).
        assert is_allowed("CPUHigh", "RestartService") is False

    def test_unknown_action_returns_false(self):
        assert is_allowed("CPUHigh", "DeleteEverything") is False

    def test_unknown_alarm_type_returns_false(self):
        assert is_allowed("UnknownAlarmType", "ScaleOut") is False

    def test_action_unknown_to_ssm_document_map_is_never_allowed(self):
        """Garde-fou : même si une action apparaissait par erreur dans
        ALLOWED_ACTIONS_BY_ALARM_TYPE sans être dans ACTION_TO_SSM_DOCUMENT,
        is_allowed doit refuser (elle ne serait pas exécutable de toute
        façon — get_ssm_document renverrait None)."""
        assert "ActionInconnue" not in ACTION_TO_SSM_DOCUMENT
        assert is_allowed("CPUHigh", "ActionInconnue") is False

    def test_every_declared_alarm_type_action_pair_is_consistent(self):
        """Chaque action citée dans ALLOWED_ACTIONS_BY_ALARM_TYPE doit avoir
        un document SSM associé, sinon elle serait whitelistée mais
        impossible à exécuter (incohérence de configuration)."""
        for alarm_type, actions in ALLOWED_ACTIONS_BY_ALARM_TYPE.items():
            for action in actions:
                assert action in ACTION_TO_SSM_DOCUMENT
                assert is_allowed(alarm_type, action) is True


class TestGetSsmDocument:
    def test_known_action_returns_document(self):
        assert get_ssm_document("RestartService") == "AWS-RunShellScript"
        assert get_ssm_document("ScaleOut") == "Custom-ScaleOutASG"
        assert get_ssm_document("RollbackDeployment") == "Custom-RollbackDeployment"

    def test_unknown_action_returns_none(self):
        assert get_ssm_document("ActionInconnue") is None
