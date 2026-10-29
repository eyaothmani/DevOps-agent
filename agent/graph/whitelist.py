from __future__ import annotations

ACTION_TO_SSM_DOCUMENT: dict[str, str] = {
    "RestartService": "AWS-RunShellScript",
    "ScaleOut": "Custom-ScaleOutASG",
    "RollbackDeployment": "Custom-RollbackDeployment",
}


ALLOWED_ACTIONS_BY_ALARM_TYPE: dict[str, set[str]] = {
    "CPUHigh": {"ScaleOut"},
    "ServiceDown": {"RestartService"},
    "HighErrorRate": {"RollbackDeployment"},
    "HealthyHostCount": {"RestartService"},
}


def is_allowed(alarm_type: str, action: str) -> bool:
    if action not in ACTION_TO_SSM_DOCUMENT:
        return False
    return action in ALLOWED_ACTIONS_BY_ALARM_TYPE.get(alarm_type, set())


def get_ssm_document(action: str) -> str | None:
    return ACTION_TO_SSM_DOCUMENT.get(action)
