from __future__ import annotations

import time

import pytest
from botocore.exceptions import ClientError

import agent.pending_validations as pv


class FakeTable:
    def __init__(self):
        self.put_items = []
        self.deleted_keys = []
        self.items = {}

    def put_item(self, Item):
        self.put_items.append(Item)
        self.items[Item["incident_id"]] = Item

    def delete_item(self, Key, ConditionExpression=None):
        incident_id = Key["incident_id"]
        if ConditionExpression is not None and incident_id not in self.items:
            raise ClientError(
                error_response={
                    "Error": {
                        "Code": "ConditionalCheckFailedException",
                        "Message": "fail",
                    }
                },
                operation_name="DeleteItem",
            )
        self.deleted_keys.append(Key)
        self.items.pop(incident_id, None)

    def scan(self, FilterExpression=None, ExpressionAttributeValues=None):
        now = ExpressionAttributeValues[":now"]
        return {
            "Items": [item for item in self.items.values() if item["expires_at"] < now]
        }


@pytest.fixture
def fake_table(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(pv, "_table", table)
    return table


class TestRegisterPendingValidation:
    def test_registers_with_expected_fields(self, fake_table, monkeypatch):
        monkeypatch.setattr(pv.settings, "VALIDATION_TIMEOUT_MINUTES", 15)
        pv.register_pending_validation("inc-1")

        assert len(fake_table.put_items) == 1
        item = fake_table.put_items[0]
        assert item["incident_id"] == "inc-1"
        assert item["expires_at"] > item["created_at"]
        assert item["ttl"] > item["expires_at"]


class TestClearPendingValidation:
    def test_deletes_by_incident_id(self, fake_table):
        fake_table.items["inc-2"] = {"incident_id": "inc-2"}
        pv.clear_pending_validation("inc-2")
        assert {"incident_id": "inc-2"} in fake_table.deleted_keys


class TestTryClaimValidationErrorPropagation:
    def test_non_conditional_check_error_is_reraised(self, monkeypatch):
        class ThrottledTable:
            def delete_item(self, Key, ConditionExpression=None):
                raise ClientError(
                    error_response={"Error": {"Code": "ThrottlingException"}},
                    operation_name="DeleteItem",
                )

        monkeypatch.setattr(pv, "_table", ThrottledTable())
        with pytest.raises(ClientError):
            pv.try_claim_validation("inc-x")


class TestListExpiredValidations:
    def test_returns_only_expired_items(self, fake_table):
        now = int(time.time())
        fake_table.items["inc-old"] = {
            "incident_id": "inc-old",
            "expires_at": now - 100,
        }
        fake_table.items["inc-fresh"] = {
            "incident_id": "inc-fresh",
            "expires_at": now + 1000,
        }

        expired = pv.list_expired_validations()

        ids = [item["incident_id"] for item in expired]
        assert "inc-old" in ids
        assert "inc-fresh" not in ids

    def test_no_expired_returns_empty_list(self, fake_table):
        now = int(time.time())
        fake_table.items["inc-fresh"] = {
            "incident_id": "inc-fresh",
            "expires_at": now + 1000,
        }
        assert pv.list_expired_validations() == []
