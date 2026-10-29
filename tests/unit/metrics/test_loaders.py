"""Unit tests for evaluation.metrics.loaders."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from evaluation.metrics import loaders as ld

# ---------------------------------------------------------------------
# load_from_dynamodb
# ---------------------------------------------------------------------


class TestLoadFromDynamodb:
    def test_paginates_through_all_pages(self):
        fake_table = MagicMock()
        fake_table.scan.side_effect = [
            {"Items": [{"incident_id": "1"}], "LastEvaluatedKey": {"k": "v"}},
            {"Items": [{"incident_id": "2"}]},
        ]

        fake_resource = MagicMock()
        fake_resource.Table.return_value = fake_table

        fake_boto3 = MagicMock()
        fake_boto3.resource.return_value = fake_resource

        with patch.dict("sys.modules", {"boto3": fake_boto3}):
            items = ld.load_from_dynamodb()

        assert items == [{"incident_id": "1"}, {"incident_id": "2"}]
        assert fake_table.scan.call_count == 2
        fake_table.scan.assert_any_call(ExclusiveStartKey={"k": "v"})

    def test_no_pagination_needed(self):
        fake_table = MagicMock()
        fake_table.scan.return_value = {"Items": [{"incident_id": "1"}]}

        fake_resource = MagicMock()
        fake_resource.Table.return_value = fake_table

        fake_boto3 = MagicMock()
        fake_boto3.resource.return_value = fake_resource

        with patch.dict("sys.modules", {"boto3": fake_boto3}):
            items = ld.load_from_dynamodb()

        assert items == [{"incident_id": "1"}]
        assert fake_table.scan.call_count == 1


# ---------------------------------------------------------------------
# load_from_golden_dataset
# ---------------------------------------------------------------------


class TestLoadFromGoldenDataset:
    def test_missing_file_raises(self, tmp_path):
        missing = tmp_path / "missing.json"

        with pytest.raises(FileNotFoundError):
            ld.load_from_golden_dataset(path=missing)

    def test_existing_file_is_parsed(self, tmp_path):
        data = [{"incident_id": "1"}]
        path = tmp_path / "golden.json"
        path.write_text(json.dumps(data), encoding="utf-8")

        result = ld.load_from_golden_dataset(path=path)

        assert result == data

    def test_non_list_content_raises_type_error(self, tmp_path):
        path = tmp_path / "golden.json"
        path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")

        with pytest.raises(TypeError):
            ld.load_from_golden_dataset(path=path)

    def test_default_path_reads_real_golden_dataset(self):
        result = ld.load_from_golden_dataset()

        assert isinstance(result, list)
        assert len(result) > 0


# ---------------------------------------------------------------------
# load_decisions
# ---------------------------------------------------------------------


class TestLoadDecisions:
    def test_mode_live_calls_dynamodb_loader(self, monkeypatch):
        monkeypatch.setattr(ld, "load_from_dynamodb", lambda: ["dynamo"])
        monkeypatch.setattr(ld, "load_from_golden_dataset", lambda: ["golden"])

        assert ld.load_decisions(mode="live") == ["dynamo"]

    def test_mode_offline_calls_golden_loader(self, monkeypatch):
        monkeypatch.setattr(ld, "load_from_dynamodb", lambda: ["dynamo"])
        monkeypatch.setattr(ld, "load_from_golden_dataset", lambda: ["golden"])

        assert ld.load_decisions(mode="offline") == ["golden"]

    def test_mode_auto_prefers_golden_when_it_exists(self, monkeypatch, tmp_path):
        golden_path = tmp_path / "golden.json"
        golden_path.write_text("[]", encoding="utf-8")

        monkeypatch.setattr(ld, "GOLDEN_DATASET_PATH", golden_path)
        monkeypatch.setattr(ld, "load_from_dynamodb", lambda: ["dynamo"])
        monkeypatch.setattr(ld, "load_from_golden_dataset", lambda: ["golden"])

        assert ld.load_decisions(mode="auto") == ["golden"]

    def test_mode_auto_falls_back_to_dynamodb_when_no_golden(
        self, monkeypatch, tmp_path
    ):
        missing_path = tmp_path / "missing.json"

        monkeypatch.setattr(ld, "GOLDEN_DATASET_PATH", missing_path)
        monkeypatch.setattr(ld, "load_from_dynamodb", lambda: ["dynamo"])
        monkeypatch.setattr(ld, "load_from_golden_dataset", lambda: ["golden"])

        assert ld.load_decisions(mode="auto") == ["dynamo"]