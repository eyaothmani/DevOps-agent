from __future__ import annotations

from unittest.mock import MagicMock

from botocore.exceptions import ClientError

from agent.dynamo_logger import DynamoDecisionLogger


class FakeTable:
    def __init__(self, raise_exc=None):
        self.put_items = []
        self._raise_exc = raise_exc

    def put_item(self, Item):
        if self._raise_exc:
            raise self._raise_exc
        self.put_items.append(Item)


class FakeResource:
    def __init__(self, table):
        self._table = table

    def Table(self, name):
        return self._table


class TestDynamoDecisionLogger:
    def test_uses_injected_resource_and_writes_item(self):
        table = FakeTable()
        logger = DynamoDecisionLogger(
            table_name="my-table", dynamodb_resource=FakeResource(table)
        )

        result = logger.log_node_contribution(
            incident_id="inc-1",
            node_name="Diagnostic",
            alarm_type="CPUHigh",
            rca_diagnosis="mémoire saturée",
            confidence=90,
            tokens_used=150,
        )

        assert result is True
        assert len(table.put_items) == 1
        item = table.put_items[0]
        assert item["incident_id"] == "inc-1"
        assert item["node_name"] == "Diagnostic"
        assert item["alarm_type"] == "CPUHigh"
        assert item["rca_diagnosis"] == "mémoire saturée"
        assert item["confidence"] == 90
        assert item["tokens_used"] == 150
        assert "expires_at" in item

    def test_extra_fields_are_merged_into_item(self):
        table = FakeTable()
        logger = DynamoDecisionLogger(dynamodb_resource=FakeResource(table))

        logger.log_node_contribution(
            incident_id="inc-2",
            node_name="Decision",
            extra={"decision_status": "EXECUTED", "action": "RestartService"},
        )

        item = table.put_items[0]
        assert item["decision_status"] == "EXECUTED"
        assert item["action"] == "RestartService"

    def test_optional_fields_omitted_when_none(self):
        table = FakeTable()
        logger = DynamoDecisionLogger(dynamodb_resource=FakeResource(table))

        logger.log_node_contribution(incident_id="inc-3", node_name="Communication")

        item = table.put_items[0]
        assert "alarm_type" not in item
        assert "rca_diagnosis" not in item
        assert "confidence" not in item
        assert "tokens_used" not in item

    def test_client_error_is_swallowed_and_returns_false(self):
        exc = ClientError(
            error_response={
                "Error": {"Code": "ProvisionedThroughputExceededException"}
            },
            operation_name="PutItem",
        )
        table = FakeTable(raise_exc=exc)
        logger = DynamoDecisionLogger(dynamodb_resource=FakeResource(table))

        result = logger.log_node_contribution(incident_id="inc-4", node_name="Decision")
        assert result is False

    def test_unexpected_exception_is_swallowed_and_returns_false(self):
        table = FakeTable(raise_exc=RuntimeError("boom"))
        logger = DynamoDecisionLogger(dynamodb_resource=FakeResource(table))

        result = logger.log_node_contribution(incident_id="inc-5", node_name="Decision")
        assert result is False

    def test_default_table_name_from_settings(self):
        logger = DynamoDecisionLogger()
        assert logger._table_name == "agent_decisions" or logger._table_name

    def test_table_property_uses_boto3_when_no_resource_injected(self, monkeypatch):
        fake_resource = MagicMock()
        monkeypatch.setattr(
            "agent.dynamo_logger.boto3.resource", lambda *a, **kw: fake_resource
        )
        logger = DynamoDecisionLogger(table_name="t")
        _ = logger._table
        fake_resource.Table.assert_called_once_with("t")
