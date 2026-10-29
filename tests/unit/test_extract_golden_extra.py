"""
Tests additionnels — evaluation/extract_golden.py

Complète tests/unit/test_extract_golden.py (qui couvre déjà les fonctions
pures _check_*, check_incident_health, _select_*) avec les fonctions
I/O et d'orchestration : _scan_all_incidents, _split_clean_and_dirty,
_status_of, _write_golden_dataset, main().

À FUSIONNER dans tests/unit/test_extract_golden.py (ou à garder comme
fichier séparé tests/unit/test_extract_golden_extra.py — les deux marchent,
pytest les découvre automatiquement).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from evaluation import extract_golden as eg


def _row(node_name, **kwargs):
    row = {"node_name": node_name}
    row.update(kwargs)
    return row


# ---------------------------------------------------------------------
# _status_of
# ---------------------------------------------------------------------


class TestStatusOf:
    def test_returns_decision_status(self):
        entry = {
            "rows": [_row("Decision", node_timestamp="1", decision_status="EXECUTED")]
        }
        assert eg._status_of(entry) == "EXECUTED"

    def test_returns_unknown_without_decision_row(self):
        entry = {"rows": [_row("Diagnostic")]}
        assert eg._status_of(entry) == "UNKNOWN"


# ---------------------------------------------------------------------
# _scan_all_incidents
# ---------------------------------------------------------------------


class TestScanAllIncidents:
    def test_paginates_and_groups_by_incident_id(self, capsys):
        table = MagicMock()
        table.scan.side_effect = [
            {
                "Items": [
                    {"incident_id": "i-1", "node_name": "Diagnostic"},
                    {"incident_id": "i-1", "node_name": "Decision"},
                ],
                "LastEvaluatedKey": {"k": "x"},
            },
            {"Items": [{"incident_id": "i-2", "node_name": "Diagnostic"}]},
        ]

        groups = eg._scan_all_incidents(table)

        assert table.scan.call_count == 2
        assert set(groups.keys()) == {"i-1", "i-2"}
        assert len(groups["i-1"]) == 2
        assert len(groups["i-2"]) == 1

    def test_rows_without_incident_id_are_skipped(self):
        table = MagicMock()
        table.scan.return_value = {"Items": [{"node_name": "Diagnostic"}]}

        groups = eg._scan_all_incidents(table)

        assert groups == {}

    def test_empty_table_returns_empty_groups(self):
        table = MagicMock()
        table.scan.return_value = {"Items": []}

        groups = eg._scan_all_incidents(table)

        assert groups == {}


# ---------------------------------------------------------------------
# _split_clean_and_dirty
# ---------------------------------------------------------------------


class TestSplitCleanAndDirty:
    def test_separates_healthy_from_unhealthy_incidents(self):
        healthy_rows = [
            _row("Diagnostic", timestamp="1000"),
            _row(
                "Decision",
                node_timestamp="2",
                timestamp="1010",
                decision_status="EXECUTED",
                confidence="95",
            ),
            _row("Communication", timestamp="1020"),
        ]
        unhealthy_rows = [_row("Diagnostic", timestamp="1000")]

        groups = {"i-healthy": healthy_rows, "i-unhealthy": unhealthy_rows}

        propres = eg._split_clean_and_dirty(groups)

        assert len(propres) == 1
        assert propres[0]["iid"] == "i-healthy"
        assert propres[0]["rows"] == healthy_rows
        assert "max_ts" in propres[0]

    def test_all_dirty_returns_empty_list(self):
        groups = {"i-1": [_row("Diagnostic", timestamp="1000")]}
        assert eg._split_clean_and_dirty(groups) == []

    def test_max_ts_defaults_to_zero_without_timestamps(self):
        healthy_rows = [
            _row("Diagnostic"),
            _row(
                "Decision",
                node_timestamp="2",
                decision_status="EXECUTED",
                confidence="95",
            ),
            _row("Communication"),
        ]
        groups = {"i-1": healthy_rows}
        propres = eg._split_clean_and_dirty(groups)
        assert propres[0]["max_ts"] == 0

    def test_prints_summary_and_top_dirty_reasons(self, capsys):
        groups = {"i-1": [_row("Diagnostic", timestamp="1000")]}
        eg._split_clean_and_dirty(groups)
        out = capsys.readouterr().out
        assert "incidents propres" in out
        assert "i-1" in out


# ---------------------------------------------------------------------
# _write_golden_dataset
# ---------------------------------------------------------------------


class TestWriteGoldenDataset:
    def test_writes_all_rows_from_selection_to_golden_path(self, tmp_path, monkeypatch):
        golden_file = tmp_path / "golden_dataset.json"
        monkeypatch.setattr(eg, "GOLDEN_PATH", str(golden_file))

        selection = [
            {
                "iid": "i-1",
                "max_ts": 1700000000,
                "rows": [
                    _row(
                        "Decision",
                        node_timestamp="1",
                        decision_status="EXECUTED",
                        alarm_type="CPUHigh",
                    )
                ],
            }
        ]

        eg._write_golden_dataset(selection)

        assert golden_file.exists()
        data = json.loads(golden_file.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["decision_status"] == "EXECUTED"

    def test_flattens_rows_across_multiple_incidents(self, tmp_path, monkeypatch):
        golden_file = tmp_path / "golden_dataset.json"
        monkeypatch.setattr(eg, "GOLDEN_PATH", str(golden_file))

        selection = [
            {
                "iid": "i-1",
                "max_ts": 100,
                "rows": [_row("Diagnostic", node_timestamp="1")],
            },
            {
                "iid": "i-2",
                "max_ts": 200,
                "rows": [
                    _row("Diagnostic", node_timestamp="1"),
                    _row("Decision", node_timestamp="2", decision_status="EXECUTED"),
                ],
            },
        ]

        eg._write_golden_dataset(selection)

        data = json.loads(golden_file.read_text(encoding="utf-8"))
        assert len(data) == 3

    def test_prints_summary_with_status_and_alarm_type(
        self, tmp_path, monkeypatch, capsys
    ):
        golden_file = tmp_path / "golden_dataset.json"
        monkeypatch.setattr(eg, "GOLDEN_PATH", str(golden_file))

        selection = [
            {
                "iid": "i-1",
                "max_ts": 1700000000,
                "rows": [
                    _row(
                        "Decision",
                        node_timestamp="1",
                        decision_status="EXECUTED",
                        alarm_type="CPUHigh",
                    )
                ],
            }
        ]

        eg._write_golden_dataset(selection)
        out = capsys.readouterr().out
        assert "i-1" in out
        assert "CPUHigh" in out
        assert "EXECUTED" in out


# ---------------------------------------------------------------------
# main() — orchestration complète
# ---------------------------------------------------------------------


class TestMain:
    def test_no_clean_incidents_skips_write(self, monkeypatch, capsys):
        monkeypatch.setattr(eg.boto3, "resource", MagicMock())
        monkeypatch.setattr(eg, "_scan_all_incidents", lambda table: {"i-1": []})
        monkeypatch.setattr(eg, "_split_clean_and_dirty", lambda groups: [])
        write_mock = MagicMock()
        monkeypatch.setattr(eg, "_write_golden_dataset", write_mock)

        eg.main()

        write_mock.assert_not_called()
        assert "ne sera PAS mis à jour" in capsys.readouterr().out

    def test_happy_path_calls_write_with_selection(self, monkeypatch):
        monkeypatch.setattr(eg.boto3, "resource", MagicMock())
        monkeypatch.setattr(eg, "_scan_all_incidents", lambda table: {"i-1": []})

        fake_entry = {
            "iid": "i-1",
            "max_ts": 100,
            "rows": [
                _row(
                    "Decision",
                    node_timestamp="1",
                    decision_status="EXECUTED",
                )
            ],
        }
        monkeypatch.setattr(eg, "_split_clean_and_dirty", lambda groups: [fake_entry])
        write_mock = MagicMock()
        monkeypatch.setattr(eg, "_write_golden_dataset", write_mock)

        eg.main()

        write_mock.assert_called_once()
        called_selection = write_mock.call_args[0][0]
        assert called_selection[0]["iid"] == "i-1"

    def test_uses_boto3_resource_and_table_name(self, monkeypatch):
        resource_mock = MagicMock()
        monkeypatch.setattr(eg.boto3, "resource", resource_mock)
        monkeypatch.setattr(eg, "_scan_all_incidents", lambda table: {})
        monkeypatch.setattr(eg, "_split_clean_and_dirty", lambda groups: [])
        monkeypatch.setattr(eg, "_write_golden_dataset", MagicMock())

        eg.main()

        resource_mock.assert_called_once_with("dynamodb")
        resource_mock.return_value.Table.assert_called_once_with(eg.TABLE_NAME)
