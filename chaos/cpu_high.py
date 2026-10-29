"""US 5.1 — Script CPU High : charge artificielle via stress-ng, durée paramétrable.

Usage autonome (un seul run) :
    python -m chaos.cpu_high --duration 300

Utilisé par chaos/run_campaign.py pour enchaîner 10 à 15 exécutions.
"""

from __future__ import annotations

import argparse
import logging
import time

from chaos import common

logger = logging.getLogger("chaos.cpu_high")

SCENARIO = "cpu_high"

_INSTALL_AND_STRESS = (
    "which stress-ng || sudo apt-get update -y && sudo apt-get install -y stress-ng"
)

# FIX #2 : "0" = stress-ng lance autant de workers que de vCPUs détectés sur
# l'instance, au lieu d'un nombre fixe (2) qui peut être insuffisant pour
# saturer une instance à plus de 2 vCPU.
_DEFAULT_WORKERS = 0


def _stress_command(duration_seconds: int, workers: int) -> list[str]:
    return [
        _INSTALL_AND_STRESS,
        f"nohup stress-ng --cpu {workers} --timeout {duration_seconds}s "
        f"> /tmp/chaos_stress.log 2>&1 &",
        "logger -t chaos-cpu-high 'stress-ng lance par le banc de test chaos (US 5.1)'",
    ]


def _kill_stress(instance_ids: list[str]) -> None:
    common.run_on_all_instances(
        instance_ids,
        ["sudo pkill -9 stress-ng || true"],
        comment="chaos-cpu-high: arret stress-ng",
    )


def run_once(
    run_index: int,
    instance_ids: list[str],
    duration_seconds: int = 300,
    workers: int = _DEFAULT_WORKERS,
    alarm_timeout_seconds: int = 480,
    recovery_timeout_seconds: int = 300,
    dynamo_grace_seconds: int = 60,
) -> common.ScenarioResult:
    # FIX #1 : le stress doit rester actif au moins aussi longtemps que le
    # délai d'attente de l'alarme (+ marge), sinon stress-ng s'arrête tout
    # seul avant même que l'alarme ait une chance de se déclencher.
    # C'est la cause racine du run raté : --duration 120 avec
    # alarm_timeout_seconds=480 par défaut.
    effective_duration = max(duration_seconds, alarm_timeout_seconds + 60)
    if effective_duration != duration_seconds:
        logger.warning(
            "[run %d] duration_seconds (%ds) < alarm_timeout_seconds+marge (%ds) : "
            "stress-ng prolongé à %ds pour rester actif pendant toute l'attente de l'alarme",
            run_index,
            duration_seconds,
            alarm_timeout_seconds + 60,
            effective_duration,
        )

    logger.info("[run %d] Vérification de l'état initial de l'alarme CPU", run_index)
    state = common.get_alarm_state(common.ALARM_CPU_HIGH)
    if state != "OK":
        logger.warning(
            "[run %d] Alarme pas en OK (%s) — nettoyage préventif", run_index, state
        )
        _kill_stress(instance_ids)
        common.wait_for_alarm_state(common.ALARM_CPU_HIGH, {"OK"}, timeout_seconds=300)

    logger.info(
        "[run %d] Lancement de stress-ng (%ds, workers=%s) sur %s",
        run_index,
        effective_duration,
        "toutes les vCPU" if workers == 0 else workers,
        instance_ids,
    )
    common.ensure_ssm_online(instance_ids)
    common.send_shell_command(
        instance_ids,
        _stress_command(effective_duration, workers),
        comment="chaos-cpu-high: injection charge CPU (US 5.1)",
    )

    t0 = time.monotonic()
    triggered, alarm_time = common.wait_for_alarm_state(
        common.ALARM_CPU_HIGH,
        {"ALARM"},
        timeout_seconds=alarm_timeout_seconds,
    )

    incident_id = None
    notes = ""
    if not triggered:
        notes = f"Alarme non déclenchée après {alarm_timeout_seconds}s"
        logger.error("[run %d] %s", run_index, notes)
    else:
        logger.info(
            "[run %d] ALARM détectée après %.0fs", run_index, time.monotonic() - t0
        )
        time.sleep(
            dynamo_grace_seconds
        )  # laisser le graphe écrire dans agent_decisions
        epoch = int(alarm_time.timestamp())
        incident_id = common.find_incident_since(epoch)
        if not incident_id:
            notes = "Alarme déclenchée mais aucun incident trouvé dans agent_decisions"
            logger.warning("[run %d] %s", run_index, notes)

    # Toujours arrêter le stress, que l'alarme ait déclenché ou non.
    _kill_stress(instance_ids)

    recovered, recovery_time = common.wait_for_alarm_state(
        common.ALARM_CPU_HIGH,
        {"OK"},
        timeout_seconds=recovery_timeout_seconds,
    )
    if triggered and not recovered:
        notes = (
            notes + " ; " if notes else ""
        ) + "Retour à OK non observé dans le délai imparti"

    return common.result_from_incident(
        scenario=SCENARIO,
        run_index=run_index,
        incident_id=incident_id,
        triggered=triggered,
        alarm_time=alarm_time,
        recovery_time=recovery_time if recovered else None,
        notes=notes,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(description="Chaos CPU High — run unique (US 5.1)")
    parser.add_argument(
        "--duration", type=int, default=300, help="Durée du stress en secondes"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=_DEFAULT_WORKERS,
        help="Nombre de workers stress-ng (0 = toutes les vCPU disponibles)",
    )
    parser.add_argument(
        "--alarm-timeout",
        type=int,
        default=480,
        help="Délai max d'attente de l'alarme CloudWatch (secondes)",
    )
    args = parser.parse_args()

    instance_ids = common.resolve_instance_ids()
    result = run_once(
        1,
        instance_ids,
        duration_seconds=args.duration,
        workers=args.workers,
        alarm_timeout_seconds=args.alarm_timeout,
    )
    common.append_csv(common.results_csv_path(SCENARIO), result.as_row())
    logger.info("Résultat : %s", result)


if __name__ == "__main__":
    main()
