import json
from pathlib import Path

import pytest

import tests as _tests_package
from agent.alarm_parser import (
    AlarmParsingError,
    _resolve_instance_id,
    parse_lambda_event,
)
from agent.models import AlarmState

FIXTURE_PATH = Path(_tests_package.__file__).parent / "fixtures" / "sample_cloudwatch_alarm.json"

@pytest.fixture
def sample_event():
    return json.loads(FIXTURE_PATH.read_text())


def test_parse_lambda_event_returns_one_alarm(sample_event):
    alarms = parse_lambda_event(sample_event)
    assert len(alarms) == 1


def test_parse_lambda_event_extracts_instance_id(sample_event):
    alarm = parse_lambda_event(sample_event)[0]
    assert alarm.instance_id == "i-0123456789abcdef0"


def test_parse_lambda_event_infers_cpu_high(sample_event):
    alarm = parse_lambda_event(sample_event)[0]
    assert alarm.alarm_type == "CPUHigh"
    assert alarm.new_state == AlarmState.ALARM


def test_parse_lambda_event_no_records_raises():
    with pytest.raises(AlarmParsingError):
        parse_lambda_event({"Records": []})


def test_parse_lambda_event_invalid_json_record_is_skipped():
    bad_event = {"Records": [{"Sns": {"Message": "not-json"}}]}
    with pytest.raises(AlarmParsingError):
        # aucun record valide => tous ignorés => erreur globale
        parse_lambda_event(bad_event)


def test_resolve_instance_id_from_target_group(monkeypatch):
    """Vérifie la résolution d'Instance ID à partir d'une dimension TargetGroup (alarme ALB)."""

    class FakeElbv2Client:
        def describe_target_health(self, TargetGroupArn):
            return {
                "TargetHealthDescriptions": [
                    {
                        "Target": {"Id": "i-0abc123def456"},
                        "TargetHealth": {"State": "healthy"},
                    }
                ]
            }

    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: FakeElbv2Client())

    trigger = {
        "Dimensions": [
            {
                "name": "TargetGroup",
                "value": "arn:aws:elasticloadbalancing:eu-north-1:...:targetgroup/eya-ec2-tg/abc123",
            },
            {"name": "LoadBalancer", "value": "app/eya-alb/xyz789"},
        ]
    }
    result = _resolve_instance_id(trigger)
    assert result == "i-0abc123def456"