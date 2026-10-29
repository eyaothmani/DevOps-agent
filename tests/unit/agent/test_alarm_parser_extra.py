from __future__ import annotations

import json

import pytest
from botocore.exceptions import ClientError

from agent.alarm_parser import (
    AlarmParsingError,
    _infer_alarm_type,
    _resolve_instance_id,
    _resolve_instance_id_from_asg,
    _resolve_instance_id_from_load_balancer,
    _resolve_instance_id_from_target_group,
    parse_lambda_event,
)


def _client_error(code="Throttling"):
    return ClientError(
        error_response={"Error": {"Code": code, "Message": "boom"}},
        operation_name="DescribeAutoScalingGroups",
    )


class TestResolveInstanceIdFromAsg:
    def test_returns_healthy_instance(self, monkeypatch):
        class FakeAsgClient:
            def describe_auto_scaling_groups(self, AutoScalingGroupNames):
                return {
                    "AutoScalingGroups": [
                        {
                            "Instances": [
                                {
                                    "InstanceId": "i-unhealthy",
                                    "HealthStatus": "Unhealthy",
                                },
                                {"InstanceId": "i-healthy", "HealthStatus": "Healthy"},
                            ]
                        }
                    ]
                }

        monkeypatch.setattr("boto3.client", lambda *a, **kw: FakeAsgClient())
        assert _resolve_instance_id_from_asg("my-asg") == "i-healthy"

    def test_returns_none_when_asg_not_found(self, monkeypatch):
        class FakeAsgClient:
            def describe_auto_scaling_groups(self, AutoScalingGroupNames):
                return {"AutoScalingGroups": []}

        monkeypatch.setattr("boto3.client", lambda *a, **kw: FakeAsgClient())
        assert _resolve_instance_id_from_asg("missing-asg") is None

    def test_returns_none_when_no_healthy_instance(self, monkeypatch):
        class FakeAsgClient:
            def describe_auto_scaling_groups(self, AutoScalingGroupNames):
                return {
                    "AutoScalingGroups": [
                        {
                            "Instances": [
                                {"InstanceId": "i-1", "HealthStatus": "Unhealthy"}
                            ]
                        }
                    ]
                }

        monkeypatch.setattr("boto3.client", lambda *a, **kw: FakeAsgClient())
        assert _resolve_instance_id_from_asg("my-asg") is None

    def test_returns_none_on_client_error(self, monkeypatch):
        class FakeAsgClient:
            def describe_auto_scaling_groups(self, AutoScalingGroupNames):
                raise _client_error()

        monkeypatch.setattr("boto3.client", lambda *a, **kw: FakeAsgClient())
        assert _resolve_instance_id_from_asg("my-asg") is None


class TestResolveInstanceIdFromTargetGroup:
    def test_full_arn_used_directly(self, monkeypatch):
        class FakeElbv2Client:
            def describe_target_health(self, TargetGroupArn):
                assert TargetGroupArn.startswith("arn:")
                return {
                    "TargetHealthDescriptions": [
                        {
                            "Target": {"Id": "i-abc"},
                            "TargetHealth": {"State": "healthy"},
                        }
                    ]
                }

        monkeypatch.setattr("boto3.client", lambda *a, **kw: FakeElbv2Client())
        result = _resolve_instance_id_from_target_group(
            "arn:aws:elasticloadbalancing:eu-north-1:123:targetgroup/tg/abc"
        )
        assert result == "i-abc"

    def test_suffix_arn_resolved_via_sts(self, monkeypatch):
        calls = {}

        class FakeStsClient:
            def get_caller_identity(self):
                return {"Account": "999999999999"}

        class FakeElbv2Client:
            def describe_target_health(self, TargetGroupArn):
                calls["arn"] = TargetGroupArn
                return {"TargetHealthDescriptions": []}

        def fake_boto_client(service, region_name=None):
            if service == "sts":
                return FakeStsClient()
            return FakeElbv2Client()

        monkeypatch.setattr("boto3.client", fake_boto_client)
        result = _resolve_instance_id_from_target_group("targetgroup/tg/abc")
        assert result is None
        assert calls["arn"].startswith("arn:aws:elasticloadbalancing:")
        assert "999999999999" in calls["arn"]

    def test_no_healthy_targets_returns_none(self, monkeypatch):
        class FakeElbv2Client:
            def describe_target_health(self, TargetGroupArn):
                return {
                    "TargetHealthDescriptions": [
                        {
                            "Target": {"Id": "i-x"},
                            "TargetHealth": {"State": "unhealthy"},
                        }
                    ]
                }

        monkeypatch.setattr("boto3.client", lambda *a, **kw: FakeElbv2Client())
        result = _resolve_instance_id_from_target_group("arn:aws:x:tg/y")
        assert result is None

    def test_returns_none_on_exception(self, monkeypatch):
        class FakeElbv2Client:
            def describe_target_health(self, TargetGroupArn):
                raise _client_error()

        monkeypatch.setattr("boto3.client", lambda *a, **kw: FakeElbv2Client())
        result = _resolve_instance_id_from_target_group("arn:aws:x:tg/y")
        assert result is None


class TestResolveInstanceIdFromLoadBalancer:
    def test_resolves_via_target_group(self, monkeypatch):
        class FakeElbv2Client:
            def describe_target_groups(self, LoadBalancerArn):
                return {
                    "TargetGroups": [{"TargetGroupArn": "arn:aws:x:targetgroup/tg/z"}]
                }

            def describe_target_health(self, TargetGroupArn):
                return {
                    "TargetHealthDescriptions": [
                        {"Target": {"Id": "i-lb"}, "TargetHealth": {"State": "healthy"}}
                    ]
                }

        monkeypatch.setattr("boto3.client", lambda *a, **kw: FakeElbv2Client())
        result = _resolve_instance_id_from_load_balancer("arn:aws:x:loadbalancer/lb/1")
        assert result == "i-lb"

    def test_no_target_groups_returns_none(self, monkeypatch):
        class FakeElbv2Client:
            def describe_target_groups(self, LoadBalancerArn):
                return {"TargetGroups": []}

        monkeypatch.setattr("boto3.client", lambda *a, **kw: FakeElbv2Client())
        result = _resolve_instance_id_from_load_balancer("arn:aws:x:loadbalancer/lb/1")
        assert result is None

    def test_returns_none_on_exception(self, monkeypatch):
        class FakeElbv2Client:
            def describe_target_groups(self, LoadBalancerArn):
                raise _client_error()

        monkeypatch.setattr("boto3.client", lambda *a, **kw: FakeElbv2Client())
        result = _resolve_instance_id_from_load_balancer("app/my-lb/xyz")
        assert result is None

    def test_short_dimension_value_builds_full_arn(self, monkeypatch):
        class FakeStsClient:
            def get_caller_identity(self):
                return {"Account": "111122223333"}

        class FakeElbv2Client:
            def describe_target_groups(self, LoadBalancerArn):
                assert "111122223333" in LoadBalancerArn
                return {"TargetGroups": []}

        def fake_boto_client(service, region_name=None):
            if service == "sts":
                return FakeStsClient()
            return FakeElbv2Client()

        monkeypatch.setattr("boto3.client", fake_boto_client)
        result = _resolve_instance_id_from_load_balancer("app/my-lb/xyz")
        assert result is None


class TestResolveInstanceId:
    def test_direct_instance_id_dimension_wins(self):
        trigger = {"Dimensions": [{"name": "InstanceId", "value": "i-direct"}]}
        assert _resolve_instance_id(trigger) == "i-direct"

    def test_no_matching_dimension_returns_none(self):
        assert _resolve_instance_id({"Dimensions": []}) is None


class TestInferAlarmType:
    @pytest.mark.parametrize(
        "metric_name,alarm_name,expected",
        [
            ("CPUUtilization", "any", "CPUHigh"),
            ("HTTPCode_Target_5XX_Count", "any", "HighErrorRate"),
            ("StatusCheckFailed", "any", "ServiceDown"),
            ("HealthyHostCount", "any", "ServiceDown"),
            ("SomeMetric", "prod-servicedown-alarm", "ServiceDown"),
            ("UnknownMetric", "generic", "UnknownMetric"),
        ],
    )
    def test_infer_alarm_type_variants(self, metric_name, alarm_name, expected):
        trigger = {"MetricName": metric_name, "Dimensions": []}
        assert _infer_alarm_type(trigger, alarm_name) == expected

    def test_infer_alarm_type_with_no_metric_falls_back_to_unknown(self):
        assert _infer_alarm_type({}, "alarm") == "Unknown"


class TestExtractTriggerMetricInfoFromMetrics:
    def test_falls_back_to_metrics_list_when_no_direct_metricname(self):
        from agent.alarm_parser import _extract_trigger_metric_info

        trigger = {
            "Metrics": [
                {
                    "MetricStat": {
                        "Metric": {
                            "MetricName": "CPUUtilization",
                            "Dimensions": [{"name": "InstanceId", "value": "i-1"}],
                        }
                    }
                }
            ]
        }
        metric_name, dims = _extract_trigger_metric_info(trigger)
        assert metric_name == "CPUUtilization"
        assert dims == [{"name": "InstanceId", "value": "i-1"}]

    def test_no_metrics_returns_none_and_empty(self):
        from agent.alarm_parser import _extract_trigger_metric_info

        metric_name, dims = _extract_trigger_metric_info({})
        assert metric_name is None
        assert dims == []


class TestResolveInstanceIdViaFullDispatch:
    def test_resolves_via_target_group_dimension(self, monkeypatch):
        class FakeElbv2Client:
            def describe_target_health(self, TargetGroupArn):
                return {
                    "TargetHealthDescriptions": [
                        {"Target": {"Id": "i-tg"}, "TargetHealth": {"State": "healthy"}}
                    ]
                }

        monkeypatch.setattr("boto3.client", lambda *a, **kw: FakeElbv2Client())
        trigger = {
            "Dimensions": [
                {"name": "TargetGroup", "value": "arn:aws:x:targetgroup/tg/1"}
            ]
        }
        assert _resolve_instance_id(trigger) == "i-tg"

    def test_resolves_via_load_balancer_dimension(self, monkeypatch):
        class FakeElbv2Client:
            def describe_target_groups(self, LoadBalancerArn):
                return {
                    "TargetGroups": [{"TargetGroupArn": "arn:aws:x:targetgroup/tg/2"}]
                }

            def describe_target_health(self, TargetGroupArn):
                return {
                    "TargetHealthDescriptions": [
                        {
                            "Target": {"Id": "i-lb2"},
                            "TargetHealth": {"State": "healthy"},
                        }
                    ]
                }

        monkeypatch.setattr("boto3.client", lambda *a, **kw: FakeElbv2Client())
        trigger = {
            "Dimensions": [
                {"name": "LoadBalancer", "value": "arn:aws:x:loadbalancer/lb/1"}
            ]
        }
        assert _resolve_instance_id(trigger) == "i-lb2"

    def _sns_event(self, message: dict) -> dict:
        return {"Records": [{"Sns": {"Message": json.dumps(message)}}]}

    def test_invalid_alarm_state_is_skipped(self):
        # NewStateValue non reconnu par l'enum AlarmState -> ValueError ->
        # record ignoré (aucune alarme valide -> AlarmParsingError globale).
        event = self._sns_event(
            {
                "AlarmName": "bad-alarm",
                "NewStateValue": "NOT_A_REAL_STATE",
                "Trigger": {"MetricName": "CPUUtilization", "Dimensions": []},
            }
        )
        with pytest.raises(AlarmParsingError):
            parse_lambda_event(event)

    def test_mixed_valid_and_invalid_records(self):
        good_message = {
            "AlarmName": "cpu-high",
            "NewStateValue": "ALARM",
            "Trigger": {"MetricName": "CPUUtilization", "Dimensions": []},
        }
        bad_message = {
            "AlarmName": "bad-alarm",
            "NewStateValue": "NOT_A_REAL_STATE",
            "Trigger": {"MetricName": "CPUUtilization", "Dimensions": []},
        }
        event = {
            "Records": [
                {"Sns": {"Message": "not-json"}},
                {"Sns": {"Message": json.dumps(bad_message)}},
                {"Sns": {"Message": json.dumps(good_message)}},
            ]
        }
        alarms = parse_lambda_event(event)
        assert len(alarms) == 1
        assert alarms[0].alarm_type == "CPUHigh"
