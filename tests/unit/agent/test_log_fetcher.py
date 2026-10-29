from __future__ import annotations

from datetime import UTC, datetime

from botocore.exceptions import ClientError

from agent import log_fetcher as lf


class TestInferSource:
    def test_syslog_stream_is_infra(self):
        assert lf._infer_source("i-abc/syslog") == "infra"

    def test_apache_stream_is_app(self):
        assert lf._infer_source("i-abc/apache-access") == "app"

    def test_unknown_stream(self):
        assert lf._infer_source("i-abc/mystery") == "unknown"


class TestParseAnchorEpochMs:
    def test_none_falls_back_to_now(self):
        result = lf._parse_anchor_epoch_ms(None)
        assert isinstance(result, int)
        assert result > 0

    def test_string_iso_with_tz(self):
        result = lf._parse_anchor_epoch_ms("2026-01-01T12:00:00+00:00")
        expected = int(
            datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC).timestamp() * 1000
        )
        assert result == expected

    def test_naive_datetime_assumed_utc(self):

        naive = datetime(2026, 1, 1, 12, 0, 0)
        result = lf._parse_anchor_epoch_ms(naive)
        expected = int(
            datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC).timestamp() * 1000
        )
        assert result == expected

    def test_aware_datetime_object(self):
        aware = datetime(2026, 6, 1, 8, 30, 0, tzinfo=UTC)
        result = lf._parse_anchor_epoch_ms(aware)
        assert result == int(aware.timestamp() * 1000)


class TestFetchFromGroup:
    def test_success_returns_sorted_entries(self):
        class FakeClient:
            def filter_log_events(self, **kwargs):
                return {
                    "events": [
                        {
                            "logStreamName": "i-1/apache-access",
                            "timestamp": 200,
                            "message": "second",
                        },
                        {
                            "logStreamName": "i-1/syslog",
                            "timestamp": 100,
                            "message": "first",
                        },
                    ]
                }

        entries = lf._fetch_from_group(FakeClient(), "loggroup", "i-1", 1000)
        assert len(entries) == 2
        assert entries[0].source == "app"
        assert entries[1].source == "infra"

    def test_resource_not_found_returns_empty(self):
        class FakeClient:
            def filter_log_events(self, **kwargs):
                raise ClientError(
                    error_response={
                        "Error": {"Code": "ResourceNotFoundException", "Message": "x"}
                    },
                    operation_name="FilterLogEvents",
                )

        entries = lf._fetch_from_group(FakeClient(), "loggroup", None, 1000)
        assert entries == []

    def test_other_client_error_returns_empty(self):
        class FakeClient:
            def filter_log_events(self, **kwargs):
                raise ClientError(
                    error_response={"Error": {"Code": "Throttling", "Message": "x"}},
                    operation_name="FilterLogEvents",
                )

        entries = lf._fetch_from_group(FakeClient(), "loggroup", None, 1000)
        assert entries == []

    def test_unexpected_exception_returns_empty(self):
        class FakeClient:
            def filter_log_events(self, **kwargs):
                raise RuntimeError("network down")

        entries = lf._fetch_from_group(FakeClient(), "loggroup", None, 1000)
        assert entries == []

    def test_instance_id_adds_stream_prefix_filter(self):
        captured = {}

        class FakeClient:
            def filter_log_events(self, **kwargs):
                captured.update(kwargs)
                return {"events": []}

        lf._fetch_from_group(FakeClient(), "loggroup", "i-42", 5000)
        assert captured["logStreamNamePrefix"] == "i-42/"


class TestFetchRecentLogs:
    def test_fetch_recent_logs_end_to_end(self, monkeypatch):
        class FakeClient:
            def filter_log_events(self, **kwargs):
                return {
                    "events": [
                        {
                            "logStreamName": "i-1/syslog",
                            "timestamp": 42,
                            "message": "hello",
                        }
                    ]
                }

        monkeypatch.setattr("boto3.client", lambda *a, **kw: FakeClient())
        entries = lf.fetch_recent_logs("i-1", around_time="2026-01-01T00:00:00+00:00")
        assert len(entries) == 1
        assert entries[0].message == "hello"


class TestFormatLogsForPrompt:
    def test_empty_logs(self):
        assert "Aucun log disponible" in lf.format_logs_for_prompt([])

    def test_formats_logs_with_source_prefix(self):
        logs = [
            lf.LogEntry(source="app", log_group="g", timestamp=1, message="  msg1  "),
            lf.LogEntry(source="infra", log_group="g", timestamp=2, message="msg2"),
        ]
        result = lf.format_logs_for_prompt(logs)
        assert "[app] msg1" in result
        assert "[infra] msg2" in result