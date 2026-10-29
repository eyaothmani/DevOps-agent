from __future__ import annotations

import json
import logging

import boto3
from botocore.exceptions import ClientError
from pydantic import ValidationError

from agent.config import settings
from agent.models import AlarmPayload, JudgeResult, RCAResult
from agent.rca_prompt import (
    JUDGE_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_judge_messages,
    build_rca_messages,
    build_retry_messages,
)

logger = logging.getLogger(__name__)


FALLBACK_RESULT = RCAResult(
    diagnosis="Diagnostic indisponible : réponse du modèle invalide après retries.",
    confidence=0,
    reasoning_steps=["Échec de validation JSON après le nombre maximal de tentatives."],
    suggested_action="RestartService",
)

FALLBACK_JUDGE_RESULT = JudgeResult(
    verdict="incertain",
    justification="Juge indisponible (échec technique ou réponse invalide).",
)


class BedrockClient:
    def __init__(self, client=None):
        self._client = client or boto3.client(
            "bedrock-runtime", region_name=settings.AWS_REGION
        )

    def _invoke(
        self,
        messages: list[dict],
        *,
        system_prompt: str = SYSTEM_PROMPT,
        model_id: str | None = None,
    ) -> tuple[str, int]:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": settings.BEDROCK_MAX_TOKENS,
            "temperature": settings.BEDROCK_TEMPERATURE,
            "system": system_prompt,
            "messages": messages,
        }
        response = self._client.invoke_model(
            modelId=model_id or settings.BEDROCK_MODEL_ID,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        payload = json.loads(response["body"].read())
        text = "".join(
            block.get("text", "")
            for block in payload.get("content", [])
            if block.get("type") == "text"
        )
        usage = payload.get("usage", {})
        tokens_used = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        return text, tokens_used

    @staticmethod
    def _strip_code_fences(raw_text: str) -> str:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = (
                cleaned.split("\n", 1)[-1]
                if cleaned.lower().startswith("json")
                else cleaned
            )
        return cleaned

    @classmethod
    def _parse_and_validate(cls, raw_text: str, alarm: AlarmPayload) -> RCAResult:
        data = json.loads(cls._strip_code_fences(raw_text))
        return RCAResult(**data)

    def diagnose(
        self,
        alarm: AlarmPayload,
        logs_text: str,
        *,
        model_id: str | None = None,
    ) -> RCAResult:
        messages = build_rca_messages(alarm, logs_text)
        last_raw_text = ""
        last_error = ""
        effective_model_id = model_id or settings.BEDROCK_MODEL_ID
        for attempt in range(1, settings.BEDROCK_MAX_RETRIES + 2):
            try:
                raw_text, tokens_used = self._invoke(
                    messages,
                    model_id=effective_model_id,
                )
                last_raw_text = raw_text

            except ClientError as exc:
                logger.exception(
                    "Erreur Bedrock (tentative %d)",
                    attempt,
                )
                last_error = str(exc)
                continue

            except Exception as exc:
                logger.exception(
                    "Erreur inattendue Bedrock (tentative %d)",
                    attempt,
                )
                last_error = str(exc)
                continue

            try:
                result = self._parse_and_validate(raw_text, alarm)
                result.model_id = effective_model_id
                result.tokens_used = tokens_used
                result.raw_response = raw_text

                logger.info(
                    "RCA validée en %d tentative(s), model=%s, confidence=%d, action=%s",
                    attempt,
                    effective_model_id,
                    result.confidence,
                    result.suggested_action,
                )

                return result

            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = str(exc)

                logger.warning(
                    "Réponse Bedrock invalide (tentative %d/%d): %s",
                    attempt,
                    settings.BEDROCK_MAX_RETRIES + 1,
                    last_error,
                )

                messages = build_retry_messages(
                    alarm,
                    logs_text,
                    raw_text,
                    last_error,
                )
        logger.error(
            "Échec définitif de la RCA après %d tentatives. Dernier texte: %s",
            settings.BEDROCK_MAX_RETRIES + 1,
            last_raw_text,
        )
        fallback = FALLBACK_RESULT.model_copy()
        fallback.raw_response = last_raw_text
        fallback.model_id = effective_model_id
        return fallback

    def judge(
        self, logs_text: str, diagnosis: str, alarm_context: str = ""
    ) -> JudgeResult:
        model_id = settings.BEDROCK_JUDGE_MODEL_ID or settings.BEDROCK_MODEL_ID
        messages = build_judge_messages(
            logs_text=logs_text,
            diagnosis=diagnosis,
            alarm_context=alarm_context,
        )

        try:
            raw_text, _ = self._invoke(
                messages, system_prompt=JUDGE_SYSTEM_PROMPT, model_id=model_id
            )
            data = json.loads(self._strip_code_fences(raw_text))
            return JudgeResult(**data)
        except (ClientError, json.JSONDecodeError, ValidationError) as exc:
            logger.warning(
                "Échec du juge LLM (best-effort, verdict neutre) : %s",
                exc,
            )
            return FALLBACK_JUDGE_RESULT.model_copy()

        except Exception:
            logger.exception("Erreur inattendue du juge LLM (best-effort)")
            return FALLBACK_JUDGE_RESULT.model_copy()
