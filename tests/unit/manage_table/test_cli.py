"""Tests — evaluation.manage_table.cli (parser argparse, dispatch, main)."""

from __future__ import annotations

from argparse import Namespace
from unittest.mock import MagicMock

from evaluation.manage_table import cli


def _base_args(**overrides):
    args = Namespace(
        inspect=False,
        schema=False,
        list_values=None,
        inspect_incident=None,
        purge=False,
        keep_latest=None,
        export_golden=False,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def test_has_command_aucune():
    assert cli.has_command(_base_args()) is False


def test_has_command_une_commande():
    assert cli.has_command(_base_args(inspect=True)) is True


def test_main_sans_commande(monkeypatch):
    monkeypatch.setattr("sys.argv", ["manage_table"])
    assert cli.main() == 1


def test_main_table_invalide(monkeypatch):
    monkeypatch.setattr("sys.argv", ["manage_table", "--inspect"])
    monkeypatch.setattr(
        cli, "get_table", lambda: (_ for _ in ()).throw(ValueError("nom invalide"))
    )
    assert cli.main() == 2


def test_main_inspect_dispatch(monkeypatch):
    table = MagicMock()
    table.table_name = "agent_decisions"
    table.key_schema = []
    table.scan.return_value = {"Items": []}

    monkeypatch.setattr("sys.argv", ["manage_table", "--inspect"])
    monkeypatch.setattr(cli, "get_table", lambda: table)

    assert cli.main() == 0


def test_main_avertit_si_reveal_sensitive(monkeypatch, caplog):
    table = MagicMock()
    table.table_name = "agent_decisions"
    table.key_schema = []
    table.scan.return_value = {"Items": []}

    monkeypatch.setattr("sys.argv", ["manage_table", "--inspect", "--reveal-sensitive"])
    monkeypatch.setattr(cli, "get_table", lambda: table)

    with caplog.at_level("WARNING"):
        cli.main()

    assert any("reveal-sensitive" in message for message in caplog.messages)