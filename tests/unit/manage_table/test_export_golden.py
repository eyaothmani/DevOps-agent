"""Tests — commande --export-golden."""

from __future__ import annotations

from evaluation.manage_table import config
from evaluation.manage_table.commands import cmd_export_golden


def test_cmd_export_golden(fake_table, tmp_path, capsys, monkeypatch):
    output_path = tmp_path / "golden.json"
    monkeypatch.setattr(config, "OUTPUT_ROOT", tmp_path.resolve())
    cmd_export_golden(fake_table, output_path, reveal_sensitive=False)
    out = capsys.readouterr().out
    assert "exportés" in out or "incomplet" in out


def test_cmd_export_golden_aucun_incident_complet(tmp_path, capsys, monkeypatch):
    from unittest.mock import MagicMock

    table = MagicMock()
    table.scan.return_value = {
        "Items": [{"incident_id": "inc-1", "node_timestamp": "t1"}]  # champs incomplets
    }
    output_path = tmp_path / "golden.json"
    monkeypatch.setattr(config, "OUTPUT_ROOT", tmp_path.resolve())

    cmd_export_golden(table, output_path, reveal_sensitive=False)

    out = capsys.readouterr().out
    assert "impossible d'exporter" in out
    assert not output_path.exists()