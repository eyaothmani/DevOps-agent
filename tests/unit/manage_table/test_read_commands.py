"""
Tests — commandes de lecture (inspect, schema, list-values, inspect-incident).

Ces tests vérifient le comportement observable (sortie console) sur une
table DynamoDB factice à deux incidents — voir conftest.fake_table.
"""

from __future__ import annotations

import pytest

from evaluation.manage_table.commands import (
    cmd_inspect,
    cmd_inspect_incident,
    cmd_list_values,
    cmd_schema,
)


def test_cmd_inspect(fake_table, capsys):
    cmd_inspect(fake_table, reveal_sensitive=False)
    out = capsys.readouterr().out
    assert "Lignes brutes scannées" in out
    assert "Incidents distincts" in out


def test_cmd_inspect_masque_les_champs_sensibles_par_defaut(fake_table, capsys):
    fake_table.scan.return_value["Items"][0]["api_key"] = "super-secret"
    cmd_inspect(fake_table, reveal_sensitive=False)
    out = capsys.readouterr().out
    assert "super-secret" not in out
    assert "***REDACTED***" in out


def test_cmd_schema(fake_table, capsys):
    cmd_schema(fake_table)
    out = capsys.readouterr().out
    assert "NODE :" in out


def test_cmd_list_values(fake_table, capsys):
    cmd_list_values(fake_table, "alarm_type")
    out = capsys.readouterr().out
    assert "CPU" in out


def test_cmd_list_values_champ_vide_refuse():
    with pytest.raises(SystemExit):
        cmd_list_values(object(), "   ")


def test_cmd_list_values_champ_sensible(fake_table):
    with pytest.raises(SystemExit):
        cmd_list_values(fake_table, "api_key")


def test_cmd_inspect_incident(fake_table, capsys):
    cmd_inspect_incident(fake_table, "inc-1", reveal_sensitive=False)
    out = capsys.readouterr().out
    assert "inc-1" in out