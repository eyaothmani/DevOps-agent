"""Unit tests for evaluation.metrics.config."""

from __future__ import annotations

import importlib
from pathlib import Path

from evaluation.metrics import config as cfg


def test_dynamo_table_name_default():
    assert cfg.DYNAMO_TABLE_NAME == "agent_decisions"


def test_golden_dataset_path_default_points_to_evaluation_dir():
    assert cfg.GOLDEN_DATASET_PATH.name == "golden_dataset.json"
    assert cfg.GOLDEN_DATASET_PATH.parent == cfg.BASE_DIR


def test_base_dir_is_evaluation_package_parent():
    assert cfg.BASE_DIR == Path(cfg.__file__).resolve().parent.parent


def test_require_judge_for_complete_is_false_by_default():
    assert cfg.REQUIRE_JUDGE_FOR_COMPLETE is False


def test_price_per_token_contains_expected_models():
    assert cfg.PRICE_PER_TOKEN == {
        "haiku": 0.00000075,
        "sonnet": 0.000009,
        "default": 0.000005,
    }


def test_dynamo_table_name_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_DECISIONS_TABLE", "custom_table")
    reloaded = importlib.reload(cfg)

    try:
        assert reloaded.DYNAMO_TABLE_NAME == "custom_table"
    finally:
        monkeypatch.delenv("AGENT_DECISIONS_TABLE", raising=False)
        importlib.reload(cfg)


def test_golden_dataset_path_env_override(monkeypatch, tmp_path):
    custom_path = tmp_path / "custom_golden.json"
    monkeypatch.setenv("GOLDEN_DATASET_PATH", str(custom_path))
    reloaded = importlib.reload(cfg)

    try:
        assert reloaded.GOLDEN_DATASET_PATH == custom_path
    finally:
        monkeypatch.delenv("GOLDEN_DATASET_PATH", raising=False)
        importlib.reload(cfg)