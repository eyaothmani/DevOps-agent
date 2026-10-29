"""
Tests — evaluation/extract_golden.py

Couvre l'ensemble du module :
- fonctions pures de diagnostic : _latest_decision_row, _check_required_nodes,
  _check_decision_status, _check_low_confidence_without_judge_disagreement,
  _check_write_spread, check_incident_health
- fonctions de sélection : _status_of, _select_success_examples,
  _add_new_status_entries, _fill_remaining_entries, _select_golden_entries
- fonctions I/O et orchestration : _scan_all_incidents, _split_clean_and_dirty,
  _write_golden_dataset, main()
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
# _latest_decision_row
# ---------------------------------------------------------------------


class TestLatestDecisionRow:
    def test_returns_none_without_decision_rows(self):
        rows = [_row("Diagnostic"), _row("Communication")]
        assert eg._latest_decision_row(rows) is None

    def test_returns_the_most_recent_decision_row(self):
        rows = [
            _row("Decision", node_timestamp="1", decision_status="LOW_CONFIDENCE_SKIPPED"),
            _row("Decision", node_timestamp="2", decision_status="EXECUTED"),
            _row("Diagnostic"),
        ]
        last = eg._latest_decision_row(rows)
        assert last["decision_status"] == "EXECUTED"

    def test_single_decision_row_is_returned(self):
        rows = [_row("Decision", node_timestamp="1", decision_status="EXECUTED")]
        assert eg._latest_decision_row(rows)["decision_status"] == "EXECUTED"


# ---------------------------------------------------------------------
# _check_required_nodes
# ---------------------------------------------------------------------


class TestCheckRequiredNodes:
    def test_none_when_all_nodes_present(self):
        assert eg._check_required_nodes({"Diagnostic", "Decision", "Communication"}) is None

    def test_reports_missing_nodes(self):
        reason = eg._check_required_nodes({"Diagnostic"})
        assert reason is not None
        assert "nodes manquants" in reason

    def test_extra_nodes_do_not_cause_a_reason(self):
        nodes = {"Diagnostic", "Decision", "Communication", "Judge"}
        assert eg._check_required_nodes(nodes) is None


# ---------------------------------------------------------------------
# _check_decision_status
# ---------------------------------------------------------------------


class TestCheckDecisionStatus:
    def test_empty_when_status_is_terminal(self):
        last_decision = {"decision_status": "EXECUTED"}
        assert eg._check_decision_status(last_decision) == []

    def test_reports_non_terminal_status(self):
        last_decision = {"decision_status": "AWAITING_HUMAN_VALIDATION"}
        raisons = eg._check_decision_status(last_decision)
        assert len(raisons) == 1
        assert "decision_status non terminal" in raisons[0]

    def test_reports_missing_status(self):
        last_decision = {}
        raisons = eg._check_decision_status(last_decision)
        assert len(raisons) == 1


# ---------------------------------------------------------------------
# _check_low_confidence_without_judge_disagreement
# ---------------------------------------------------------------------


class TestCheckLowConfidenceWithoutJudgeDisagreement:
    def test_none_when_status_is_not_executed(self):
        last_decision = {"decision_status": "REFUSED_BY_WHITELIST", "confidence": "50"}
        assert eg._check_low_confidence_without_judge_disagreement(last_decision, []) is None

    def test_none_when_confidence_is_missing_or_invalid(self):
        last_decision = {"decision_status": "EXECUTED", "confidence": "not-a-number"}
        assert eg._check_low_confidence_without_judge_disagreement(last_decision, []) is None

    def test_none_when_confidence_is_high_enough(self):
        last_decision = {"decision_status": "EXECUTED", "confidence": "90"}
        assert eg._check_low_confidence_without_judge_disagreement(last_decision, []) is None

    def test_reports_low_confidence_without_judge_disagreement(self):
        last_decision = {"decision_status": "EXECUTED", "confidence": "70"}
        reason = eg._check_low_confidence_without_judge_disagreement(last_decision, [])
        assert reason is not None
        assert "sans désaccord" in reason

    def test_none_when_judge_documented_a_disagreement(self):
        last_decision = {"decision_status": "EXECUTED", "confidence": "70"}
        rows = [_row("Judge", judge_verdict="incoherent")]
        assert eg._check_low_confidence_without_judge_disagreement(last_decision, rows) is None

    def test_reports_when_judge_verdict_is_coherent(self):
        last_decision = {"decision_status": "EXECUTED", "confidence": "70"}
        rows = [_row("Judge", judge_verdict="coherent")]
        reason = eg._check_low_confidence_without_judge_disagreement(last_decision, rows)
        assert reason is not None


# ---------------------------------------------------------------------
# _check_write_spread
# ---------------------------------------------------------------------


class TestCheckWriteSpread:
    def test_none_without_timestamps(self):
        assert eg._check_write_spread([_row("Diagnostic")]) is None

    def test_none_when_spread_is_within_one_hour(self):
        rows = [_row("Diagnostic", timestamp="1000"), _row("Communication", timestamp="4000")]
        assert eg._check_write_spread(rows) is None

    def test_reports_spread_above_one_hour(self):
        rows = [_row("Diagnostic", timestamp="1000"), _row("Communication", timestamp="5000")]
        reason = eg._check_write_spread(rows)
        assert reason is not None
        assert "étalement" in reason

    def test_none_when_timestamps_are_not_convertible(self):
        rows = [_row("Diagnostic", timestamp="not-a-float")]
        assert eg._check_write_spread(rows) is None


# ---------------------------------------------------------------------
# check_incident_health — comportement intégré
# ---------------------------------------------------------------------


class TestCheckIncidentHealth:
    def test_fully_healthy_incident(self):
        rows = [
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
        ok, raisons = eg.check_incident_health(rows)
        assert ok is True
        assert raisons == []

    def test_missing_nodes_makes_incident_unhealthy(self):
        rows = [_row("Diagnostic", timestamp="1000")]
        ok, raisons = eg.check_incident_health(rows)
        assert ok is False
        assert any("nodes manquants" in r for r in raisons)

    def test_missing_decision_row_is_reported(self):
        rows = [_row("Diagnostic"), _row("Communication")]
        ok, raisons = eg.check_incident_health(rows)
        assert ok is False
        assert any("aucune row Decision trouvée" in r for r in raisons)

    def test_non_terminal_decision_status_is_reported(self):
        rows = [
            _row("Diagnostic"),
            _row("Decision", node_timestamp="1", decision_status="AWAITING_HUMAN_VALIDATION"),
            _row("Communication"),
        ]
        ok, raisons = eg.check_incident_health(rows)
        assert ok is False
        assert any("decision_status non terminal" in r for r in raisons)

    def test_low_confidence_without_judge_disagreement_is_reported(self):
        rows = [
            _row("Diagnostic"),
            _row("Decision", node_timestamp="1", decision_status="EXECUTED", confidence="70"),
            _row("Communication"),
        ]
        ok, raisons = eg.check_incident_health(rows)
        assert ok is False
        assert any("sans désaccord" in r for r in raisons)

    def test_low_confidence_with_judge_disagreement_is_healthy(self):
        rows = [
            _row("Diagnostic"),
            _row("Decision", node_timestamp="1", decision_status="EXECUTED", confidence="70"),
            _row("Judge", judge_verdict="incoherent"),
            _row("Communication"),
        ]
        # tests/unit/test_extract_golden.py:214
        ok, _raisons = eg.check_incident_health(rows)  # au lieu de "ok, raisons ="
        assert ok is True

    def test_write_spread_too_large_is_reported(self):
        rows = [
            _row("Diagnostic", timestamp="1000"),
            _row(
                "Decision",
                node_timestamp="1",
                decision_status="EXECUTED",
                confidence="95",
                timestamp="1000",
            ),
            _row("Communication", timestamp="4700"),
        ]
        ok, raisons = eg.check_incident_health(rows)
        assert ok is False
        assert any("étalement" in r for r in raisons)

    def test_multiple_reasons_accumulate(self):
        rows = [_row("Diagnostic")]
        ok, raisons = eg.check_incident_health(rows)
        assert ok is False
        assert len(raisons) >= 2  # nodes manquants + aucune row Decision


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
# _select_success_examples
# ---------------------------------------------------------------------


class TestSelectSuccessExamples:
    def test_returns_up_to_two_success_entries_in_order(self):
        entries_sorted = [
            {"iid": "a", "rows": [_row("Decision", node_timestamp="1", decision_status="LOW_CONFIDENCE_SKIPPED")]},
            {"iid": "b", "rows": [_row("Decision", node_timestamp="1", decision_status="EXECUTED")]},
            {"iid": "c", "rows": [_row("Decision", node_timestamp="1", decision_status="AUTO_REMEDIATED")]},
            {"iid": "d", "rows": [_row("Decision", node_timestamp="1", decision_status="EXECUTED")]},
        ]
        result = eg._select_success_examples(entries_sorted)
        assert [e["iid"] for e in result] == ["b", "c"]

    def test_returns_empty_and_warns_without_any_success(self, capsys):
        entries_sorted = [
            {"iid": "a", "rows": [_row("Decision", node_timestamp="1", decision_status="REFUSED_BY_WHITELIST")]},
        ]
        result = eg._select_success_examples(entries_sorted)
        assert result == []
        assert "ATTENTION" in capsys.readouterr().out

    def test_single_success_entry_is_returned(self):
        entries_sorted = [
            {"iid": "a", "rows": [_row("Decision", node_timestamp="1", decision_status="EXECUTED")]},
        ]
        result = eg._select_success_examples(entries_sorted)
        assert [e["iid"] for e in result] == ["a"]


# ---------------------------------------------------------------------
# _add_new_status_entries
# ---------------------------------------------------------------------


class TestAddNewStatusEntries:
    def test_skips_entries_already_in_selection(self):
        a = {"iid": "a", "rows": [_row("Decision", node_timestamp="1", decision_status="EXECUTED")]}
        b = {"iid": "b", "rows": [_row("Decision", node_timestamp="1", decision_status="EXECUTED")]}
        c = {"iid": "c", "rows": [_row("Decision", node_timestamp="1", decision_status="REFUSED_BY_WHITELIST")]}
        entries_sorted = [a, b, c]
        selection = [a]
        statuts_vus = {"EXECUTED"}

        eg._add_new_status_entries(entries_sorted, selection, statuts_vus, target=3)

        assert [e["iid"] for e in selection] == ["a", "c"]

    def test_stops_once_target_is_reached(self):
        a = {"iid": "a", "rows": [_row("Decision", node_timestamp="1", decision_status="EXECUTED")]}
        b = {"iid": "b", "rows": [_row("Decision", node_timestamp="1", decision_status="REFUSED_BY_WHITELIST")]}
        c = {"iid": "c", "rows": [_row("Decision", node_timestamp="1", decision_status="AUTO_REMEDIATED")]}
        entries_sorted = [a, b, c]
        selection = []
        statuts_vus = set()

        eg._add_new_status_entries(entries_sorted, selection, statuts_vus, target=2)

        assert len(selection) == 2


# ---------------------------------------------------------------------
# _fill_remaining_entries
# ---------------------------------------------------------------------


class TestFillRemainingEntries:
    def test_fills_up_to_target_with_any_remaining_entry(self):
        a = {"iid": "a"}
        b = {"iid": "b"}
        c = {"iid": "c"}
        entries_sorted = [a, b, c]
        selection = [a]

        eg._fill_remaining_entries(entries_sorted, selection, target=3)

        assert [e["iid"] for e in selection] == ["a", "b", "c"]

    def test_stops_once_target_is_reached(self):
        a = {"iid": "a"}
        b = {"iid": "b"}
        c = {"iid": "c"}
        entries_sorted = [a, b, c]
        selection = []

        eg._fill_remaining_entries(entries_sorted, selection, target=2)

        assert len(selection) == 2

    def test_no_op_when_all_entries_already_selected(self):
        a = {"iid": "a"}
        entries_sorted = [a]
        selection = [a]

        eg._fill_remaining_entries(entries_sorted, selection, target=5)

        assert len(selection) == 1


# ---------------------------------------------------------------------
# _select_golden_entries — orchestration complète de la sélection
# ---------------------------------------------------------------------


class TestSelectGoldenEntries:
    def test_prioritizes_success_then_diversity(self):
        e1 = {"iid": "e1", "max_ts": 100, "rows": [_row("Decision", node_timestamp="1", decision_status="EXECUTED")]}
        e2 = {"iid": "e2", "max_ts": 200, "rows": [_row("Decision", node_timestamp="1", decision_status="REFUSED_BY_WHITELIST")]}
        e3 = {"iid": "e3", "max_ts": 300, "rows": [_row("Decision", node_timestamp="1", decision_status="AUTO_REMEDIATED")]}
        e4 = {"iid": "e4", "max_ts": 50, "rows": [_row("Decision", node_timestamp="1", decision_status="DUPLICATE_ACTION_SKIPPED")]}
        e5 = {"iid": "e5", "max_ts": 400, "rows": [_row("Decision", node_timestamp="1", decision_status="REJECTED_BY_HUMAN")]}
        propres = [e1, e2, e3, e4, e5]

        entries_sorted, selection = eg._select_golden_entries(propres)

        # tri par max_ts décroissant
        assert [e["iid"] for e in entries_sorted] == ["e5", "e3", "e2", "e1", "e4"]

        # succès (e3, e1) en priorité, puis diversité de statuts (e5, e2, e4)
        assert [e["iid"] for e in selection] == ["e3", "e1", "e5", "e2", "e4"]
        assert len(selection) == eg.NB_INCIDENTS_CIBLE

    def test_falls_back_to_fill_when_not_enough_diversity(self):
        f1 = {"iid": "f1", "max_ts": 10, "rows": [_row("Decision", node_timestamp="1", decision_status="EXECUTED")]}
        f2 = {"iid": "f2", "max_ts": 20, "rows": [_row("Decision", node_timestamp="1", decision_status="EXECUTED")]}
        propres = [f1, f2]

        _, selection = eg._select_golden_entries(propres)

        # pas assez d'incidents distincts pour atteindre NB_INCIDENTS_CIBLE
        assert [e["iid"] for e in selection] == ["f2", "f1"]
        assert len(selection) == 2

    def test_single_entry(self):
        f1 = {"iid": "f1", "max_ts": 10, "rows": [_row("Decision", node_timestamp="1", decision_status="EXECUTED")]}
        _, selection = eg._select_golden_entries([f1])
        assert [e["iid"] for e in selection] == ["f1"]


# ---------------------------------------------------------------------
# _scan_all_incidents
# ---------------------------------------------------------------------


class TestScanAllIncidents:
    def test_paginates_and_groups_by_incident_id(self):
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

    def test_unknown_alarm_type_falls_back_to_placeholder(
        self, tmp_path, monkeypatch, capsys
    ):
        golden_file = tmp_path / "golden_dataset.json"
        monkeypatch.setattr(eg, "GOLDEN_PATH", str(golden_file))

        selection = [
            {
                "iid": "i-1",
                "max_ts": 1700000000,
                "rows": [_row("Decision", node_timestamp="1", decision_status="EXECUTED")],
            }
        ]

        eg._write_golden_dataset(selection)
        out = capsys.readouterr().out
        assert "?" in out


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