from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, wait

import pytest
from botocore.exceptions import ClientError

import agent.pending_validations as pv


class FakeDynamoDBTableThreadSafe:
    def __init__(self):
        self._items: dict[str, dict] = {}
        self._lock = threading.Lock()

    def put_item(self, Item):
        with self._lock:
            self._items[Item["incident_id"]] = dict(Item)
        return {}

    def delete_item(self, Key, ConditionExpression=None):
        incident_id = Key["incident_id"]
        with self._lock:
            if ConditionExpression is not None and incident_id not in self._items:
                raise ClientError(
                    error_response={
                        "Error": {
                            "Code": "ConditionalCheckFailedException",
                            "Message": "The conditional request failed",
                        }
                    },
                    operation_name="DeleteItem",
                )
            self._items.pop(incident_id, None)
        return {}


@pytest.fixture
def fake_table(monkeypatch):
    table = FakeDynamoDBTableThreadSafe()
    monkeypatch.setattr(pv, "_table", table)
    return table


class TestTryClaimValidationConcurrency:
    def test_single_caller_claims_successfully(self, fake_table):
        fake_table.put_item(
            {"incident_id": "inc-solo", "created_at": 0, "expires_at": 999}
        )
        assert pv.try_claim_validation("inc-solo") is True

    def test_second_call_after_claim_fails(self, fake_table):
        fake_table.put_item(
            {"incident_id": "inc-seq", "created_at": 0, "expires_at": 999}
        )
        assert pv.try_claim_validation("inc-seq") is True

        assert pv.try_claim_validation("inc-seq") is False

    def test_claim_on_unknown_incident_returns_false(self, fake_table):

        assert pv.try_claim_validation("inc-never-registered") is False

    def test_true_concurrent_double_call_only_one_wins(self, fake_table):

        incident_id = "inc-race-double"
        fake_table.put_item(
            {"incident_id": incident_id, "created_at": 0, "expires_at": 999}
        )

        barrier = threading.Barrier(2)

        def _claim():
            barrier.wait()
            return pv.try_claim_validation(incident_id)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_claim) for _ in range(2)]
            _done, _ = wait(futures)
            results = [f.result() for f in futures]

        assert sorted(results) == [
            False,
            True,
        ], f"Attendu exactement un gagnant sur 2 appels concurrents, obtenu={results}"

    def test_true_concurrent_many_callers_exactly_one_wins(self, fake_table):

        incident_id = "inc-race-many"
        n_callers = 25
        fake_table.put_item(
            {"incident_id": incident_id, "created_at": 0, "expires_at": 999}
        )

        barrier = threading.Barrier(n_callers)

        def _claim():
            barrier.wait()
            return pv.try_claim_validation(incident_id)

        with ThreadPoolExecutor(max_workers=n_callers) as pool:
            futures = [pool.submit(_claim) for _ in range(n_callers)]
            _done, _ = wait(futures)
            results = [f.result() for f in futures]
        assert results.count(True) == 1, (
            f"Attendu exactement 1 gagnant sur {n_callers} appels concurrents, "
            f"obtenu {results.count(True)} gagnant(s)"
        )
        assert results.count(False) == n_callers - 1

    def test_two_different_incidents_both_claimed_independently(self, fake_table):
        """Garde-fou négatif : deux incidents DIFFÉRENTS réclamés en
        parallèle ne doivent PAS se bloquer mutuellement — le verrouillage
        doit être scopé par incident_id, pas global."""
        fake_table.put_item(
            {"incident_id": "inc-a", "created_at": 0, "expires_at": 999}
        )
        fake_table.put_item(
            {"incident_id": "inc-b", "created_at": 0, "expires_at": 999}
        )

        barrier = threading.Barrier(2)

        def _claim(incident_id):
            barrier.wait()
            return pv.try_claim_validation(incident_id)

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_a = pool.submit(_claim, "inc-a")
            f_b = pool.submit(_claim, "inc-b")
            wait([f_a, f_b])

        assert f_a.result() is True
        assert f_b.result() is True
