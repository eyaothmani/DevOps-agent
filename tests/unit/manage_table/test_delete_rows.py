"""
Tests — evaluation.manage_table.commands.delete_rows.

Couvre les confirmations interactives (normale / majeure / non-interactive)
et la suppression individuelle d'une ligne (succès, clé absente, erreur AWS).
"""

from __future__ import annotations

# Ensure project root is on sys.path so tests can import the evaluated package
import os
import sys
from unittest.mock import MagicMock

# move up three levels from tests/unit/manage_table to reach project root
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
src_path = os.path.join(project_root, "src")

if src_path not in sys.path:
    sys.path.insert(0, src_path)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from botocore.exceptions import ClientError

from evaluation.manage_table import config
from evaluation.manage_table.commands.delete_rows import (
    confirm_destructive,
    delete_one_row,
)

# ---------------------------------------------------------------------------
# Confirmations
# ---------------------------------------------------------------------------


def test_confirm_normal_deletion_oui(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "oui")
    assert confirm_destructive(
        [{"incident_id": "x"}], total_in_table=100, label="Purge"
    )


def test_confirm_normal_deletion_non(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "non")
    result = confirm_destructive(
        [{"incident_id": "x"}], total_in_table=100, label="Purge"
    )
    assert result is False


def test_confirm_major_deletion_ok(monkeypatch):
    monkeypatch.setattr(config, "TABLE_NAME", "agent_decisions")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "agent_decisions")
    rows = [{"incident_id": f"i{i}"} for i in range(9)]
    assert confirm_destructive(rows, total_in_table=10, label="Purge") is True


def test_confirm_major_deletion_refuse(monkeypatch):
    monkeypatch.setattr(config, "TABLE_NAME", "agent_decisions")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "mauvais_nom")
    rows = [{"incident_id": f"i{i}"} for i in range(9)]
    assert confirm_destructive(rows, total_in_table=10, label="Purge") is False


def test_confirm_destructive_non_interactif(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    result = confirm_destructive(
        [{"incident_id": "x"}], total_in_table=10, label="Purge"
    )
    assert result is False
    assert "non interactive" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Suppression d'une ligne
# ---------------------------------------------------------------------------


def test_delete_one_row_cle_absente():
    table = MagicMock()
    table.key_schema = [{"AttributeName": "incident_id", "KeyType": "HASH"}]
    deleted, errors = delete_one_row(table, {}, deleted=0, errors=0)
    assert deleted == 0
    assert errors == 1


def test_delete_one_row_client_error():
    table = MagicMock()
    table.key_schema = [{"AttributeName": "incident_id", "KeyType": "HASH"}]
    table.delete_item.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException"}}, "DeleteItem"
    )
    deleted, errors = delete_one_row(
        table, {"incident_id": "inc-1"}, deleted=0, errors=0
    )
    assert deleted == 0
    assert errors == 1


def test_delete_one_row_erreur_dynamodb_generique():
    table = MagicMock()
    table.key_schema = [{"AttributeName": "incident_id", "KeyType": "HASH"}]
    table.delete_item.side_effect = ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException"}}, "DeleteItem"
    )
    deleted, errors = delete_one_row(
        table, {"incident_id": "inc-1"}, deleted=0, errors=0
    )
    assert deleted == 0
    assert errors == 1


def test_delete_one_row_succes():
    table = MagicMock()
    table.key_schema = [{"AttributeName": "incident_id", "KeyType": "HASH"}]
    deleted, errors = delete_one_row(
        table, {"incident_id": "inc-1"}, deleted=0, errors=0
    )
    assert deleted == 1
    assert errors == 0
    table.delete_item.assert_called_once()