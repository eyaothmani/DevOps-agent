from __future__ import annotations

from unittest.mock import MagicMock

from botocore.exceptions import ClientError

from agent.graph import freshness as fr


def _alarm(name="cpu-high-web"):
    alarm = MagicMock()
    alarm.alarm_name = name
    return alarm


class TestCheckStillRelevant:
    def test_cloudwatch_error_returns_unknown_fail_open(self, monkeypatch):
        class FakeCw:
            def describe_alarms(self, AlarmNames):
                raise ClientError(
                    error_response={"Error": {"Code": "Throttling"}},
                    operation_name="DescribeAlarms",
                )

        monkeypatch.setattr(fr, "_cloudwatch", FakeCw())
        result = fr.check_still_relevant(_alarm(), "RestartService")
        assert result.verdict == fr.FreshnessVerdict.UNKNOWN
        assert result.current_alarm_state is None

    def test_alarm_not_found_returns_unknown(self, monkeypatch):
        class FakeCw:
            def describe_alarms(self, AlarmNames):
                return {"MetricAlarms": []}

        monkeypatch.setattr(fr, "_cloudwatch", FakeCw())
        result = fr.check_still_relevant(_alarm(), "RestartService")
        assert result.verdict == fr.FreshnessVerdict.UNKNOWN

    def test_action_proposed_but_alarm_resolved(self, monkeypatch):
        class FakeCw:
            def describe_alarms(self, AlarmNames):
                return {"MetricAlarms": [{"StateValue": "OK"}]}

        monkeypatch.setattr(fr, "_cloudwatch", FakeCw())
        result = fr.check_still_relevant(_alarm(), "RestartService")
        assert result.verdict == fr.FreshnessVerdict.ALARM_RESOLVED
        assert result.current_alarm_state == "OK"

    def test_no_action_but_alarm_still_active_is_worsened(self, monkeypatch):
        class FakeCw:
            def describe_alarms(self, AlarmNames):
                return {"MetricAlarms": [{"StateValue": "ALARM"}]}

        monkeypatch.setattr(fr, "_cloudwatch", FakeCw())
        result = fr.check_still_relevant(_alarm(), "NONE")
        assert result.verdict == fr.FreshnessVerdict.ALARM_WORSENED
        assert result.current_alarm_state == "ALARM"

    def test_unchanged_situation_is_still_relevant(self, monkeypatch):
        class FakeCw:
            def describe_alarms(self, AlarmNames):
                return {"MetricAlarms": [{"StateValue": "ALARM"}]}

        monkeypatch.setattr(fr, "_cloudwatch", FakeCw())
        result = fr.check_still_relevant(_alarm(), "RestartService")
        assert result.verdict == fr.FreshnessVerdict.STILL_RELEVANT
        assert result.current_alarm_state == "ALARM"

    def test_no_action_and_alarm_ok_is_still_relevant(self, monkeypatch):
        class FakeCw:
            def describe_alarms(self, AlarmNames):
                return {"MetricAlarms": [{"StateValue": "OK"}]}

        monkeypatch.setattr(fr, "_cloudwatch", FakeCw())
        result = fr.check_still_relevant(_alarm(), "NONE")
        assert result.verdict == fr.FreshnessVerdict.STILL_RELEVANT
