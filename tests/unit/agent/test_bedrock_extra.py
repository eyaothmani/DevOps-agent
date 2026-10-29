from __future__ import annotations

import io
import json
from unittest.mock import MagicMock

from botocore.exceptions import ClientError

from agent.bedrock_client import FALLBACK_JUDGE_RESULT, BedrockClient
from agent.models import AlarmPayload, AlarmState, JudgeVerdict


def _make_alarm():
    return AlarmPayload(
        alarm_name="CPUHigh-web-01",
        alarm_type="CPUHigh",
        new_state=AlarmState.ALARM,
        instance_id="i-0123456789abcdef0",
    )


def _bedrock_body(content_text: str, input_tokens=100, output_tokens=50):
    payload = {
        "content": [{"type": "text", "text": content_text}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }
    return {"body": io.BytesIO(json.dumps(payload).encode())}


class TestStripCodeFences:
    def test_strips_json_fenced_block(self):
        raw = '```json\n{"a": 1}\n```'
        assert BedrockClient._strip_code_fences(raw).strip() == '{"a": 1}'

    def test_strips_plain_fenced_block(self):
        raw = '```\n{"a": 1}\n```'
        result = BedrockClient._strip_code_fences(raw)
        assert result.strip() == '{"a": 1}'

    def test_no_fence_passthrough(self):
        raw = '{"a": 1}'
        assert BedrockClient._strip_code_fences(raw) == '{"a": 1}'


class TestDiagnoseClientError:
    def test_client_error_triggers_retry_then_fallback(self):
        mock_client = MagicMock()
        mock_client.invoke_model.side_effect = ClientError(
            error_response={"Error": {"Code": "ThrottlingException"}},
            operation_name="InvokeModel",
        )

        client = BedrockClient(client=mock_client)
        result = client.diagnose(_make_alarm(), "logs de test")

        assert result.confidence == 0
        assert mock_client.invoke_model.call_count >= 1

    def test_client_error_then_success(self):
        valid_json = json.dumps(
            {
                "diagnosis": "OK",
                "confidence": 80,
                "reasoning_steps": ["x"],
                "suggested_action": "ScaleOut",
            }
        )
        mock_client = MagicMock()
        mock_client.invoke_model.side_effect = [
            ClientError(
                error_response={"Error": {"Code": "ThrottlingException"}},
                operation_name="InvokeModel",
            ),
            _bedrock_body(valid_json),
        ]

        client = BedrockClient(client=mock_client)
        result = client.diagnose(_make_alarm(), "logs de test")
        assert result.confidence == 80


class TestJudge:
    def test_judge_returns_parsed_verdict(self):
        judge_json = json.dumps(
            {
                "verdict": "coherent",
                "justification": "Diagnostic cohérent avec les logs.",
            }
        )
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = _bedrock_body(judge_json)

        client = BedrockClient(client=mock_client)
        result = client.judge(logs_text="logs", diagnosis="CPU saturé")

        assert result.verdict == JudgeVerdict.COHERENT
        assert "cohérent" in result.justification

    def test_judge_client_error_returns_neutral_fallback(self):
        mock_client = MagicMock()
        mock_client.invoke_model.side_effect = ClientError(
            error_response={"Error": {"Code": "ThrottlingException"}},
            operation_name="InvokeModel",
        )

        client = BedrockClient(client=mock_client)
        result = client.judge(logs_text="logs", diagnosis="diag")

        assert result.verdict == FALLBACK_JUDGE_RESULT.verdict
        assert result.justification == FALLBACK_JUDGE_RESULT.justification

    def test_judge_invalid_json_returns_neutral_fallback(self):
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = _bedrock_body("not valid json")

        client = BedrockClient(client=mock_client)
        result = client.judge(logs_text="logs", diagnosis="diag")

        assert result.verdict == FALLBACK_JUDGE_RESULT.verdict

    def test_judge_unexpected_exception_returns_neutral_fallback(self):
        mock_client = MagicMock()
        mock_client.invoke_model.side_effect = RuntimeError("boom")

        client = BedrockClient(client=mock_client)
        result = client.judge(logs_text="logs", diagnosis="diag")

        assert result.verdict == FALLBACK_JUDGE_RESULT.verdict

    def test_judge_uses_dedicated_model_id_when_configured(self, monkeypatch):
        monkeypatch.setattr(
            "agent.bedrock_client.settings.BEDROCK_JUDGE_MODEL_ID", "judge-model-x"
        )
        judge_json = json.dumps({"verdict": "incertain", "justification": "n/a"})
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = _bedrock_body(judge_json)

        client = BedrockClient(client=mock_client)
        client.judge(logs_text="logs", diagnosis="diag")

        _, kwargs = mock_client.invoke_model.call_args
        assert kwargs["modelId"] == "judge-model-x"
