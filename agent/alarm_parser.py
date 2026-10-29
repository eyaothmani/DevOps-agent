from __future__ import annotations

import json
import logging
from typing import Any

import boto3

from agent.config import settings
from agent.models import AlarmPayload, AlarmState

logger = logging.getLogger(__name__)


class AlarmParsingError(Exception):
    """Levée quand le payload SNS ne peut pas être interprété comme une alarme CloudWatch."""


def _extract_trigger_metric_info(
    trigger: dict[str, Any],
) -> tuple[str | None, list[dict[str, Any]]]:
    metric_name = trigger.get("MetricName")
    dimensions = trigger.get("Dimensions")

    if metric_name or dimensions:
        return metric_name, dimensions or []

    for metric_wrapper in trigger.get("Metrics") or []:
        metric_stat = metric_wrapper.get("MetricStat")
        if not metric_stat:
            continue

        metric = metric_stat.get("Metric", {})
        metric_name = metric.get("MetricName")
        dimensions = metric.get("Dimensions")

        if metric_name or dimensions:
            return metric_name, dimensions or []

    return None, []


def _resolve_instance_id_from_asg(asg_name: str) -> str | None:
    """Résout une instance saine à partir d'un nom d'Auto Scaling Group."""
    try:
        asg_client = boto3.client(
            "autoscaling",
            region_name=settings.AWS_REGION,
        )

        response = asg_client.describe_auto_scaling_groups(
            AutoScalingGroupNames=[asg_name]
        )

        groups = response.get("AutoScalingGroups", [])

        if not groups:
            logger.warning(
                "ASG '%s' introuvable, instance_id non résolu",
                asg_name,
            )
            return None

        healthy_instances = [
            instance["InstanceId"]
            for instance in groups[0].get("Instances", [])
            if instance.get("HealthStatus") == "Healthy"
        ]

        if not healthy_instances:
            logger.warning(
                "Aucune instance saine dans l'ASG '%s'",
                asg_name,
            )
            return None

        instance_id = healthy_instances[0]

        logger.info(
            "Instance résolue via ASG -> asg=%s instance_id=%s",
            asg_name,
            instance_id,
        )

        return instance_id

    except Exception:
        logger.exception(
            "Échec de résolution de l'ASG '%s' en instance_id",
            asg_name,
        )
        return None


def _resolve_instance_id_from_target_group(
    target_group_arn: str,
) -> str | None:
    """Résout une instance saine à partir d'un Target Group d'ALB.

    La dimension CloudWatch peut fournir un ARN suffixe
    (ex: 'targetgroup/...'). Cette fonction le transforme en ARN complet
    avant d'appeler describe_target_health.
    """
    try:
        target_group_arn = _ensure_target_group_arn(target_group_arn)

        elbv2_client = boto3.client(
            "elbv2",
            region_name=settings.AWS_REGION,
        )

        response = elbv2_client.describe_target_health(TargetGroupArn=target_group_arn)

        healthy_instances = [
            target["Target"]["Id"]
            for target in response.get("TargetHealthDescriptions", [])
            if target.get("TargetHealth", {}).get("State") == "healthy"
        ]

        if not healthy_instances:
            logger.warning(
                "Aucune cible saine dans le Target Group '%s'",
                target_group_arn,
            )
            return None

        instance_id = healthy_instances[0]

        logger.info(
            "Instance résolue via Target Group -> target_group=%s instance_id=%s",
            target_group_arn,
            instance_id,
        )

        return instance_id

    except Exception:
        logger.exception(
            "Échec de résolution du Target Group '%s' en instance_id",
            target_group_arn,
        )
        return None


def _ensure_target_group_arn(target_group_arn: str) -> str:
    """Reconstruit un ARN complet lorsqu'un suffixe est fourni."""
    if target_group_arn.startswith("arn:"):
        return target_group_arn

    sts_client = boto3.client(
        "sts",
        region_name=settings.AWS_REGION,
    )

    account_id = sts_client.get_caller_identity()["Account"]

    return (
        f"arn:aws:elasticloadbalancing:"
        f"{settings.AWS_REGION}:{account_id}:"
        f"{target_group_arn}"
    )


def _build_load_balancer_arn(lb_dimension_value: str) -> str:
    """Reconstruit l'ARN complet d'un Load Balancer."""
    if lb_dimension_value.startswith("arn:"):
        return lb_dimension_value

    sts_client = boto3.client(
        "sts",
        region_name=settings.AWS_REGION,
    )

    account_id = sts_client.get_caller_identity()["Account"]

    return (
        f"arn:aws:elasticloadbalancing:"
        f"{settings.AWS_REGION}:{account_id}:"
        f"loadbalancer/{lb_dimension_value}"
    )


def _resolve_instance_id_from_load_balancer(
    lb_dimension_value: str,
) -> str | None:
    """Résout une instance saine à partir de la dimension LoadBalancer."""
    try:
        lb_arn = _build_load_balancer_arn(lb_dimension_value)

        elbv2_client = boto3.client(
            "elbv2",
            region_name=settings.AWS_REGION,
        )

        response = elbv2_client.describe_target_groups(LoadBalancerArn=lb_arn)

        groups = response.get("TargetGroups", [])

        if not groups:
            logger.warning(
                "Aucun Target Group rattaché au LoadBalancer '%s'",
                lb_arn,
            )
            return None

        target_group_arn = groups[0]["TargetGroupArn"]

        return _resolve_instance_id_from_target_group(target_group_arn)

    except Exception:
        logger.exception(
            "Échec de résolution du LoadBalancer '%s' en instance_id",
            lb_dimension_value,
        )
        return None


def _resolve_instance_id(trigger: dict[str, Any]) -> str | None:
    """Résout un Instance ID réel à partir des Dimensions de l'alarme."""
    _, dimensions_list = _extract_trigger_metric_info(trigger)

    dimensions = {
        dimension.get("name"): dimension.get("value") for dimension in dimensions_list
    }

    instance_id = dimensions.get("InstanceId")
    if instance_id:
        return instance_id

    resolvers = (
        (
            "AutoScalingGroupName",
            _resolve_instance_id_from_asg,
        ),
        (
            "TargetGroup",
            _resolve_instance_id_from_target_group,
        ),
        (
            "LoadBalancer",
            _resolve_instance_id_from_load_balancer,
        ),
    )

    for dimension_name, resolver in resolvers:
        dimension_value = dimensions.get(dimension_name)

        if dimension_value:
            return resolver(dimension_value)

    return None


def _infer_alarm_type(
    trigger: dict[str, Any],
    alarm_name: str = "",
) -> str:
    """Déduit un type d'alarme métier à partir du nom de métrique CloudWatch."""
    metric_name_raw, _ = _extract_trigger_metric_info(trigger)
    metric_name_lower = (metric_name_raw or "").lower()

    if "cpu" in metric_name_lower:
        return "CPUHigh"

    if "5xx" in metric_name_lower or "httpcode" in metric_name_lower:
        return "HighErrorRate"

    if "statuscheck" in metric_name_lower:
        return "ServiceDown"

    if metric_name_raw == "HealthyHostCount" or "servicedown" in alarm_name.lower():
        return "ServiceDown"

    return metric_name_raw or "Unknown"


def _build_alarm_payload(
    message: dict[str, Any],
) -> AlarmPayload:
    """Construit et valide un AlarmPayload depuis un message SNS."""
    trigger = message.get("Trigger", {})
    alarm_name = message.get("AlarmName", "Unknown")
    metric_name, _ = _extract_trigger_metric_info(trigger)

    return AlarmPayload(
        alarm_name=alarm_name,
        alarm_type=_infer_alarm_type(trigger, alarm_name),
        new_state=AlarmState(message.get("NewStateValue", "ALARM")),
        reason=message.get("NewStateReason"),
        region=message.get("Region"),
        instance_id=_resolve_instance_id(trigger),
        metric_name=metric_name,
        namespace=trigger.get("Namespace"),
        threshold=trigger.get("Threshold"),
        raw_message=message,
    )


def _parse_sns_record(record: dict[str, Any]) -> AlarmPayload | None:
    """Parse un record SNS individuel."""
    sns = record.get("Sns", {})
    raw_message = sns.get("Message")

    try:
        message = json.loads(raw_message)
    except (TypeError, json.JSONDecodeError):
        logger.warning("Record SNS ignoré (message non-JSON)")
        return None

    try:
        return _build_alarm_payload(message)
    except Exception:  # noqa: BLE001
        logger.warning("Record SNS ignoré (payload alarme invalide)")
    return None


def parse_lambda_event(
    event: dict[str, Any],
) -> list[AlarmPayload]:
    """Parse un event Lambda déclenché par SNS."""
    records = event.get("Records") or []

    if not records:
        raise AlarmParsingError(
            "Aucun Record dans l'événement Lambda (event SNS vide)."
        )

    alarms: list[AlarmPayload] = []

    for record in records:
        alarm = _parse_sns_record(record)

        if alarm is not None:
            alarms.append(alarm)

    if not alarms:
        raise AlarmParsingError(
            "Aucune alarme valide n'a pu être extraite de l'événement."
        )

    return alarms
