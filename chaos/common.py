"""US 5.1 — Utilitaires partagés du banc de test d'injection d'incidents.

Ce module centralise ce qui est commun aux 3 scénarios de chaos engineering
(CPU High, Service Down, High Error Rate) : résolution dynamique des
instances EC2, envoi/attente de commandes SSM, attente d'un état d'alarme
CloudWatch, et extraction des incidents traités depuis la table
`agent_decisions` (US 2.4) pour alimenter les métriques (US 5.2).

Toutes les commandes AWS sont exécutées avec les identifiants du poste qui
lance le script (aws cli / variables d'environnement), pas avec le rôle de
l'agent Lambda.
"""

from __future__ import annotations

import csv
import dataclasses
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

# --- Configuration (mêmes conventions que agent/config.py) -----------------
AWS_REGION: str = os.getenv("AWS_REGION", "eu-north-1")
ASG_NAME: str = os.getenv("CHAOS_ASG_NAME", "eya-asg")
AGENT_DECISIONS_TABLE: str = os.getenv("AGENT_DECISIONS_TABLE", "agent_decisions")

# Alarmes CloudWatch réellement déployées (infra/cloudwatch.tf)
ALARM_CPU_HIGH: str = "eya-asg-cpu-high"
ALARM_SERVICE_DOWN: str = "eya-servicedown"
ALARM_HIGH_ERROR_RATE: str = "eya-alb-5xx-rate-high"

RESULTS_DIR = Path(__file__).parent / "results"


def _client(service: str):
    return boto3.client(service, region_name=AWS_REGION)


def ssm_client():
    return _client("ssm")


def cw_client():
    return _client("cloudwatch")


def autoscaling_client():
    return _client("autoscaling")


def resolve_alb_dns(alb_name: str = "eya-alb") -> str:
    client = _client("elbv2")
    resp = client.describe_load_balancers(Names=[alb_name])
    return resp["LoadBalancers"][0]["DNSName"]


def dynamodb_table():
    resource = boto3.resource("dynamodb", region_name=AWS_REGION)
    return resource.Table(AGENT_DECISIONS_TABLE)


# --- Résolution des instances -----------------------------------------------
def resolve_instance_ids(asg_name: str = ASG_NAME) -> list[str]:
    """Retourne les instances saines de l'ASG (source de vérité, plutôt que
    des IDs codés en dur qui deviennent obsolètes à chaque redéploiement)."""
    client = autoscaling_client()
    response = client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
    groups = response.get("AutoScalingGroups", [])
    if not groups:
        raise RuntimeError(f"ASG '{asg_name}' introuvable.")
    healthy = [
        i["InstanceId"]
        for i in groups[0].get("Instances", [])
        if i.get("HealthStatus") == "Healthy"
    ]
    if not healthy:
        raise RuntimeError(f"Aucune instance saine dans l'ASG '{asg_name}'.")
    return healthy


def ensure_ssm_online(
    instance_ids: list[str], timeout_seconds: int = 60, poll_interval: int = 5
) -> None:
    """Vérifie que l'agent SSM est bien Online sur toutes les instances
    avant d'envoyer une commande — évite d'attendre inutilement le
    timeout de l'alarme (480s) quand une instance vient de redémarrer et
    que son agent SSM n'a pas encore reconnecté (US 5.1 — fiabilité du
    banc de test)."""
    client = ssm_client()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        resp = client.describe_instance_information(
            Filters=[{"Key": "InstanceIds", "Values": instance_ids}]
        )
        statuses = {
            i["InstanceId"]: i.get("PingStatus")
            for i in resp.get("InstanceInformationList", [])
        }
        if all(statuses.get(iid) == "Online" for iid in instance_ids):
            return
        time.sleep(poll_interval)
    raise RuntimeError(
        f"Instances non joignables via SSM après {timeout_seconds}s : {statuses}. "
        "Vérifie qu'elles ne sont pas en cours de redémarrage/remplacement ASG."
    )


# --- SSM ---------------------------------------------------------------------
def send_shell_command(
    instance_ids: list[str],
    commands: list[str],
    comment: str,
    timeout_seconds: int = 120,
) -> str:
    client = ssm_client()
    response = client.send_command(
        InstanceIds=instance_ids,
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands},
        Comment=comment,
        TimeoutSeconds=timeout_seconds,
    )
    return response["Command"]["CommandId"]


def wait_command_done(
    command_id: str, instance_id: str, timeout_seconds: int = 60
) -> str:
    """Poll jusqu'à un statut terminal. Retourne le statut (Success/Failed/...)."""
    client = ssm_client()
    deadline = time.monotonic() + timeout_seconds
    status = "Pending"
    while time.monotonic() < deadline:
        try:
            resp = client.get_command_invocation(
                CommandId=command_id, InstanceId=instance_id
            )
            status = resp.get("Status", "Pending")
            if status not in ("Pending", "InProgress", "Delayed"):
                return status
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "InvocationDoesNotExist":
                raise
        time.sleep(3)
    return status


def run_on_all_instances(
    instance_ids: list[str], commands: list[str], comment: str
) -> None:
    """Envoie une commande shell à toutes les instances et attend qu'elle termine
    partout (best-effort : n'échoue pas le scénario si une instance traîne)."""
    command_id = send_shell_command(instance_ids, commands, comment)
    for instance_id in instance_ids:
        wait_command_done(command_id, instance_id)


# --- Alarmes CloudWatch -------------------------------------------------------
def get_alarm_state(alarm_name: str) -> str | None:
    client = cw_client()
    resp = client.describe_alarms(AlarmNames=[alarm_name])
    alarms = resp.get("MetricAlarms", [])
    if not alarms:
        return None
    return alarms[0].get("StateValue")


def wait_for_alarm_state(
    alarm_name: str,
    target_states: set[str],
    timeout_seconds: int,
    poll_interval: int = 15,
) -> tuple[bool, datetime | None]:
    """Attend que l'alarme atteigne un des états cibles. Retourne
    (atteint, horodatage_utc_de_detection)."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        state = get_alarm_state(alarm_name)
        if state in target_states:
            return True, datetime.now(timezone.utc)
        time.sleep(poll_interval)
    return False, None


# --- Extraction des incidents depuis agent_decisions (US 2.4 / US 5.2) ------
def find_incident_since(epoch_seconds: int, grace_seconds: int = 30) -> str | None:
    """Scan léger (projection minimale) pour trouver le premier incident_id
    apparu après un timestamp donné. Utilisé juste après la détection d'une
    alarme pour identifier l'incident que l'agent vient de traiter."""
    table = dynamodb_table()
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "ProjectionExpression": "incident_id, #ts",
        "ExpressionAttributeNames": {"#ts": "timestamp"},
        "FilterExpression": "#ts >= :since",
        "ExpressionAttributeValues": {":since": epoch_seconds - grace_seconds},
    }
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    if not items:
        return None
    items.sort(key=lambda it: int(it["timestamp"]))
    return str(items[0]["incident_id"])


def fetch_incident_nodes(incident_id: str) -> dict[str, dict[str, Any]]:
    """Récupère tous les nodes journalisés pour un incident_id donné
    (query efficace via la clé de partition), indexés par node_name.
    Si plusieurs contributions existent pour un même node (rare), la
    dernière (par node_timestamp) est conservée."""
    table = dynamodb_table()
    from boto3.dynamodb.conditions import Key

    resp = table.query(KeyConditionExpression=Key("incident_id").eq(incident_id))
    nodes: dict[str, dict[str, Any]] = {}
    for item in resp.get("Items", []):
        nodes[item["node_name"]] = item
    return nodes


# --- Résultats -----------------------------------------------------------------
@dataclasses.dataclass
class ScenarioResult:
    scenario: str
    run_index: int
    incident_id: str | None
    triggered: bool
    alarm_time: datetime | None
    recovery_time: datetime | None
    mttr_seconds: float | None
    confidence: int | None
    decision_status: str | None
    action: str | None
    judge_verdict: str | None
    groundedness_score: float | None
    model_id: str | None
    tokens_used: int | None
    communication_status: str | None
    notes: str = ""

    def as_row(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["alarm_time"] = self.alarm_time.isoformat() if self.alarm_time else ""
        d["recovery_time"] = (
            self.recovery_time.isoformat() if self.recovery_time else ""
        )
        return d


def result_from_incident(
    scenario: str,
    run_index: int,
    incident_id: str | None,
    triggered: bool,
    alarm_time: datetime | None,
    recovery_time: datetime | None,
    notes: str = "",
) -> ScenarioResult:
    diag = decision = judge = comm = {}
    if incident_id:
        nodes = fetch_incident_nodes(incident_id)
        diag = nodes.get("Diagnostic", {})
        decision = nodes.get("Decision", {})
        judge = nodes.get("Judge", {})
        comm = nodes.get("Communication", {})

    mttr = None
    if alarm_time and recovery_time:
        mttr = round((recovery_time - alarm_time).total_seconds(), 2)

    return ScenarioResult(
        scenario=scenario,
        run_index=run_index,
        incident_id=incident_id,
        triggered=triggered,
        alarm_time=alarm_time,
        recovery_time=recovery_time,
        mttr_seconds=mttr,
        confidence=int(diag["confidence"])
        if diag.get("confidence") is not None
        else None,
        decision_status=decision.get("decision_status"),
        action=decision.get("action"),
        judge_verdict=judge.get("judge_verdict"),
        groundedness_score=float(diag["groundedness_score"])
        if diag.get("groundedness_score") is not None
        else None,
        model_id=diag.get("model_id"),
        tokens_used=int(diag["tokens_used"])
        if diag.get("tokens_used") is not None
        else None,
        communication_status=comm.get("communication_status"),
        notes=notes,
    )


def append_csv(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def results_csv_path(scenario: str) -> Path:
    return RESULTS_DIR / f"{scenario}_results.csv"
