"""Tests — commandes destructives --purge et --keep-latest."""

from __future__ import annotations

from unittest.mock import MagicMock

from evaluation.manage_table import config
from evaluation.manage_table.commands import cmd_keep_latest, cmd_purge

# ---------------------------------------------------------------------------
# Dry-run (aucune suppression réelle)
# ---------------------------------------------------------------------------


def test_cmd_purge_dry_run(fake_table, capsys):
    cmd_purge(fake_table, keep_after=None, dry_run=True)
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    fake_table.delete_item.assert_not_called()


def test_cmd_keep_latest_dry_run(fake_table, capsys):
    cmd_keep_latest(fake_table, n=1, dry_run=True)
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    fake_table.delete_item.assert_not_called()


def test_cmd_purge_avec_keep_after(capsys):
    table = MagicMock()
    table.scan.return_value = {
        "Items": [
            {"incident_id": "old", "node_timestamp": "t1", "timestamp": 100},
            {"incident_id": "new", "node_timestamp": "t2", "timestamp": 9999999999},
        ]
    }
    cmd_purge(table, keep_after="2024-01-01T00:00:00Z", dry_run=True)
    out = capsys.readouterr().out
    assert "Purge" in out


# ---------------------------------------------------------------------------
# Suppression réelle
# ---------------------------------------------------------------------------


def test_cmd_purge_suppression_reelle(monkeypatch):
    table = MagicMock()
    table.scan.return_value = {
        "Items": [
            # 1 seule ligne ancienne (avant le cutoff) -> sera supprimée
            {"incident_id": "inc-old", "node_timestamp": "t0", "timestamp": 100},
            # 9 lignes "futures" (timestamp Unix loin dans le futur) -> conservées
            *(
                {
                    "incident_id": f"inc-{i}",
                    "node_timestamp": f"t{i}",
                    "timestamp": 9999999999,
                }
                for i in range(1, 10)
            ),
        ]
    }
    table.key_schema = [{"AttributeName": "incident_id", "KeyType": "HASH"}]
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "oui")

    # Seule inc-old est avant le cutoff -> 1/10 = 10% < seuil de 90%
    # -> confirmation "normale" ('oui' suffit)
    cmd_purge(table, keep_after="2024-06-01T00:00:00Z", dry_run=False)

    table.delete_item.assert_called_once()


def test_cmd_purge_suppression_majeure(monkeypatch):
    """Ratio de suppression >= 90% -> exige de taper le nom de la table."""
    table = MagicMock()
    table.scan.return_value = {
        "Items": [{"incident_id": "inc-1", "node_timestamp": "t1", "timestamp": 100}]
    }
    table.key_schema = [{"AttributeName": "incident_id", "KeyType": "HASH"}]
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(config, "TABLE_NAME", "agent_decisions")
    monkeypatch.setattr("builtins.input", lambda _: "agent_decisions")

    cmd_purge(table, keep_after=None, dry_run=False)

    table.delete_item.assert_called_once()


def test_cmd_keep_latest_suppression_reelle(monkeypatch):
    table = MagicMock()
    table.scan.return_value = {
        "Items": [
            {
                "incident_id": "inc-1",
                "node_timestamp": "t1",
                "timestamp": 100,
                "decision_status": "EXECUTED",
            },
            {
                "incident_id": "inc-2",
                "node_timestamp": "t2",
                "timestamp": 200,
                "decision_status": "EXECUTED",
            },
        ]
    }
    table.key_schema = [{"AttributeName": "incident_id", "KeyType": "HASH"}]
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "oui")
    cmd_keep_latest(table, n=1, dry_run=False)
    table.delete_item.assert_called()