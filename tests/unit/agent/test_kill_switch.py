from unittest.mock import MagicMock

from botocore.exceptions import ClientError

from agent.kill_switch import KILL_SWITCH_PARAMETER_NAME, KillSwitch


def _ssm_response(value: str) -> dict:
    return {"Parameter": {"Value": value}}


class TestKillSwitchIsAgentEnabled:
    def test_returns_true_when_parameter_is_enabled(self):
        client = MagicMock()
        client.get_parameter.return_value = _ssm_response("ENABLED")
        ks = KillSwitch(ssm_client=client)

        assert ks.is_agent_enabled() is True
        client.get_parameter.assert_called_once_with(Name=KILL_SWITCH_PARAMETER_NAME)

    def test_returns_false_when_parameter_is_disabled(self):
        client = MagicMock()
        client.get_parameter.return_value = _ssm_response("DISABLED")
        ks = KillSwitch(ssm_client=client)

        assert ks.is_agent_enabled() is False

    def test_value_is_case_and_whitespace_insensitive(self):
        client = MagicMock()
        client.get_parameter.return_value = _ssm_response("  enabled  ")
        ks = KillSwitch(ssm_client=client)

        assert ks.is_agent_enabled() is True

    def test_any_other_value_is_treated_as_disabled(self):
        client = MagicMock()
        client.get_parameter.return_value = _ssm_response("maybe")
        ks = KillSwitch(ssm_client=client)

        assert ks.is_agent_enabled() is False

    def test_client_error_fails_closed(self):
        client = MagicMock()
        client.get_parameter.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "nope"}},
            "GetParameter",
        )
        ks = KillSwitch(ssm_client=client)

        assert ks.is_agent_enabled() is False

    def test_unexpected_exception_fails_closed(self):
        client = MagicMock()
        client.get_parameter.side_effect = RuntimeError("boom")
        ks = KillSwitch(ssm_client=client)

        assert ks.is_agent_enabled() is False

    def test_parameter_not_found_fails_closed(self):
        client = MagicMock()
        client.get_parameter.side_effect = ClientError(
            {"Error": {"Code": "ParameterNotFound", "Message": "missing"}},
            "GetParameter",
        )
        ks = KillSwitch(ssm_client=client)

        assert ks.is_agent_enabled() is False


class TestKillSwitchConstruction:
    def test_uses_injected_client_without_calling_boto3(self):
        client = MagicMock()
        ks = KillSwitch(ssm_client=client)
        assert ks._client is client

    def test_default_client_is_created_lazily_via_boto3(self, monkeypatch):
        sentinel_client = MagicMock()
        create_client = MagicMock(return_value=sentinel_client)
        monkeypatch.setattr("agent.kill_switch.boto3.client", create_client)

        ks = KillSwitch()

        assert ks._client is sentinel_client
        create_client.assert_called_once()
        assert create_client.call_args.args[0] == "ssm"
