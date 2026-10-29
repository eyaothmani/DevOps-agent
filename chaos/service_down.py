from __future__ import annotations

import argparse
import logging
import time

from chaos import common

logger = logging.getLogger("chaos.service_down")

SCENARIO = "service_down"


def _stop_apache(instance_ids: list[str]) -> None:
    common.run_on_all_instances(
        instance_ids,
        [
            "logger -t chaos-service-down 'Arret Apache par le banc de test chaos (US 5.1)'",
            "sudo systemctl stop apache2",
        ],
        comment="chaos-service-down: arret Apache (US 5.1)",
    )


def _start_apache(instance_ids: list[str]) -> None:
    common.run_on_all_instances(
        instance_ids,
        ["sudo systemctl start apache2"],
        comment="chaos-service-down: redemarrage Apache",
    )


def run_once(
    run_index: int,
    instance_ids: list[str],
    outage_duration_seconds: int = 90,
    alarm_timeout_seconds: int = 240,
    recovery_timeout_seconds: int = 300,
    dynamo_grace_seconds: int = 60,
) -> common.ScenarioResult:
    # Toutes les instances doivent être coupées pour que HealthyHostCount tombe
    # à 0 (une seule instance saine suffit à maintenir l'ALB en bonne santé).
    logger.info(
        "[run %d] Vérification de l'état initial de l'alarme ServiceDown", run_index
    )
    state = common.get_alarm_state(common.ALARM_SERVICE_DOWN)
    if state != "OK":
        logger.warning(
            "[run %d] Alarme pas en OK (%s) — on s'assure qu'Apache tourne",
            run_index,
            state,
        )
        _start_apache(instance_ids)
        common.wait_for_alarm_state(
            common.ALARM_SERVICE_DOWN, {"OK"}, timeout_seconds=300
        )

    logger.info("[run %d] Arrêt d'Apache sur %s", run_index, instance_ids)
    _stop_apache(instance_ids)

    t0 = time.monotonic()
    triggered, alarm_time = common.wait_for_alarm_state(
        common.ALARM_SERVICE_DOWN,
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
        # On respecte au minimum la durée de panne demandée avant de restaurer,
        # pour laisser le temps au graphe de traiter l'incident.
        elapsed = time.monotonic() - t0
        if elapsed < outage_duration_seconds:
            time.sleep(outage_duration_seconds - elapsed)
        time.sleep(dynamo_grace_seconds)
        epoch = int(alarm_time.timestamp())
        incident_id = common.find_incident_since(epoch)
        if not incident_id:
            notes = "Alarme déclenchée mais aucun incident trouvé dans agent_decisions"
            logger.warning("[run %d] %s", run_index, notes)

    logger.info("[run %d] Redémarrage d'Apache", run_index)
    _start_apache(instance_ids)

    recovered, recovery_time = common.wait_for_alarm_state(
        common.ALARM_SERVICE_DOWN,
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
    parser = argparse.ArgumentParser(
        description="Chaos Service Down — run unique (US 5.1)"
    )
    parser.add_argument(
        "--outage-duration", type=int, default=90, help="Durée minimale de la panne (s)"
    )
    args = parser.parse_args()

    instance_ids = common.resolve_instance_ids()
    result = run_once(1, instance_ids, outage_duration_seconds=args.outage_duration)
    common.append_csv(common.results_csv_path(SCENARIO), result.as_row())
    logger.info("Résultat : %s", result)


if __name__ == "__main__":
    main()
