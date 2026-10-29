import io
import json
from unittest.mock import MagicMock

from agent.bedrock_client import BedrockClient
from agent.models import AlarmPayload, AlarmState


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
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }
    return {"body": io.BytesIO(json.dumps(payload).encode())}


def test_diagnose_valid_json_first_try():
    valid_json = json.dumps(
        {
            "diagnosis": "Fuite de mémoire sur le processus nginx",
            "confidence": 92,
            "reasoning_steps": ["CPU > 90%", "Logs montrent OOM répétés"],
            "suggested_action": "RestartService",
        }
    )
    mock_client = MagicMock()
    mock_client.invoke_model.return_value = _bedrock_body(valid_json)

    client = BedrockClient(client=mock_client)
    result = client.diagnose(_make_alarm(), "logs de test")

    assert result.confidence == 92
    assert result.suggested_action == "RestartService"
    assert result.tokens_used == 150
    mock_client.invoke_model.assert_called_once()


def test_diagnose_retries_then_succeeds():
    invalid_json = "ceci n'est pas du JSON"
    valid_json = json.dumps(
        {
            "diagnosis": "Taux d'erreur 5xx élevé",
            "confidence": 70,
            "reasoning_steps": ["Taux 5xx > 5%"],
            "suggested_action": "RollbackDeployment",
        }
    )
    mock_client = MagicMock()
    mock_client.invoke_model.side_effect = [
        _bedrock_body(invalid_json),
        _bedrock_body(valid_json),
    ]

    client = BedrockClient(client=mock_client)
    result = client.diagnose(_make_alarm(), "logs de test")

    assert result.confidence == 70
    assert mock_client.invoke_model.call_count == 2


def test_diagnose_falls_back_after_max_retries():
    invalid_json = "toujours invalide"
    mock_client = MagicMock()
    mock_client.invoke_model.return_value = _bedrock_body(invalid_json)

    client = BedrockClient(client=mock_client)
    result = client.diagnose(_make_alarm(), "logs de test")

    assert result.confidence == 0
    # "NONE" n'est plus une valeur acceptée par RCAResult.suggested_action
    # (voir models.py) : le fallback de bedrock_client.py utilise désormais
    # l'action la plus prudente ("RestartService") comme filet de sécurité,
    # confidence=0 forçant de toute façon une escalade humaine (US 4.1/4.8)
    # avant toute exécution réelle. Voir FALLBACK_RESULT dans bedrock_client.py.
    assert result.suggested_action == "RestartService"
