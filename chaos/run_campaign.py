from __future__ import annotations

import argparse
import logging
import time

from chaos import common, cpu_high, high_error_rate, service_down

logger = logging.getLogger("chaos.run_campaign")

DEFAULT_COOLDOWN_SECONDS = 90


def run_campaign(
    scenario: str, runs: int, cooldown_seconds: int, **scenario_kwargs
) -> list[common.ScenarioResult]:
    instance_ids = common.resolve_instance_ids()
    logger.info("Instances ciblées : %s", instance_ids)

    results: list[common.ScenarioResult] = []
    csv_path = common.results_csv_path(scenario)

    for run_index in range(1, runs + 1):
        logger.info("=== %s — run %d/%d ===", scenario, run_index, runs)
        try:
            if scenario == "cpu_high":
                result = cpu_high.run_once(run_index, instance_ids, **scenario_kwargs)
            elif scenario == "service_down":
                result = service_down.run_once(
                    run_index, instance_ids, **scenario_kwargs
                )
            elif scenario == "high_error_rate":
                alb_dns = (
                    scenario_kwargs.pop("alb_dns", None) or common.resolve_alb_dns()
                )
                result = high_error_rate.run_once(
                    run_index, instance_ids, alb_dns, **scenario_kwargs
                )
            else:
                raise ValueError(f"Scénario inconnu : {scenario}")
        except Exception:
            logger.exception(
                "Run %d échoué avec une exception non gérée — on continue la campagne",
                run_index,
            )
            continue

        results.append(result)
        common.append_csv(csv_path, result.as_row())
        logger.info(
            "Run %d terminé : incident_id=%s mttr=%ss statut=%s",
            run_index,
            result.incident_id,
            result.mttr_seconds,
            result.decision_status,
        )

        if run_index < runs:
            logger.info("Pause de %ds avant le run suivant", cooldown_seconds)
            time.sleep(cooldown_seconds)

    triggered_count = sum(1 for r in results if r.triggered)
    logger.info(
        "Campagne '%s' terminée : %d/%d runs ont déclenché l'alarme. Résultats : %s",
        scenario,
        triggered_count,
        runs,
        csv_path,
    )
    return results


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(
        description="Campagne de chaos engineering (US 5.1)"
    )
    parser.add_argument(
        "--scenario",
        required=True,
        choices=["cpu_high", "service_down", "high_error_rate"],
    )
    parser.add_argument(
        "--runs", type=int, default=12, help="Nombre d'exécutions (10-15 recommandé)"
    )
    parser.add_argument(
        "--cooldown",
        type=int,
        default=DEFAULT_COOLDOWN_SECONDS,
        help="Pause entre runs (s)",
    )
    # Paramètres spécifiques passés tels quels aux run_once() des scénarios
    parser.add_argument("--duration", type=int, help="cpu_high : durée du stress (s)")
    parser.add_argument(
        "--alarm-timeout",
        type=int,
        help="cpu_high/service_down : délai max d'attente de l'alarme (s) — "
        "réduisez-le une fois les temps réels connus pour raccourcir la campagne",
    )
    parser.add_argument(
        "--outage-duration", type=int, help="service_down : durée min. de la panne (s)"
    )
    parser.add_argument(
        "--rate", type=float, help="high_error_rate : taux d'erreur injecté (0-1)"
    )
    args = parser.parse_args()

    kwargs = {}
    if args.scenario == "cpu_high":
        if args.duration:
            kwargs["duration_seconds"] = args.duration
        if args.alarm_timeout:
            kwargs["alarm_timeout_seconds"] = args.alarm_timeout
    if args.scenario == "service_down":
        if args.outage_duration:
            kwargs["outage_duration_seconds"] = args.outage_duration
        if args.alarm_timeout:
            kwargs["alarm_timeout_seconds"] = args.alarm_timeout
    if args.scenario == "high_error_rate" and args.rate is not None:
        kwargs["error_rate"] = args.rate

    run_campaign(args.scenario, args.runs, args.cooldown, **kwargs)


if __name__ == "__main__":
    main()
