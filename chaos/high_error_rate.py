from __future__ import annotations

import argparse
import logging
import threading
import time

import requests

from chaos import common

logger = logging.getLogger("chaos.high_error_rate")

SCENARIO = "high_error_rate"

_MARKER = "/etc/chaos5xx_deployed"

# FIX : /tmp est isolé par PrivateTmp=yes sur le service apache2 (confirmé
# via `systemctl show apache2 -p PrivateTmp`). Le processus CGI (lancé par
# Apache) ne voit donc jamais les écritures faites via SSM dans le /tmp
# "réel" — d'où un rate toujours lu comme absent (except -> 0.0) et un
# taux d'erreur qui reste à 0% quoi qu'on écrive. /etc n'est pas concerné
# par cette isolation et reste world-readable par défaut (644).
_RATE_FILE = "/etc/chaos5xx_rate"

_CGI_SCRIPT = rf"""#!/usr/bin/env python3
import random
print("Content-Type: text/plain")
try:
    with open("{_RATE_FILE}") as f:
        rate = float(f.read().strip() or "0")
except Exception:
    rate = 0.0
if random.random() < rate:
    print("Status: 500 Internal Server Error")
    print("")
    print("chaos-injected-error")
else:
    print("Status: 200 OK")
    print("")
    print("ok")
"""

_DEPLOY_COMMANDS = [
    f"test -f {_MARKER} && exit 0 || true",
    "sudo apt-get update -y && sudo apt-get install -y apache2",
    "sudo a2enmod cgi",
    "sudo a2enconf serve-cgi-bin",  # FIX bonus : nécessaire sur certaines images
    # Ubuntu pour que /cgi-bin/ soit servi en dehors du DocumentRoot par défaut.
    f"cat << 'CHAOSEOF' | sudo tee /usr/lib/cgi-bin/chaos5xx.py > /dev/null\n{_CGI_SCRIPT}CHAOSEOF",
    "sudo chmod +x /usr/lib/cgi-bin/chaos5xx.py",
    f"echo 0 | sudo tee {_RATE_FILE} > /dev/null",
    f"sudo chmod 644 {_RATE_FILE}",  # lisible par www-data (le CGI ne tourne pas en root)
    "sudo systemctl restart apache2",
    f"sudo touch {_MARKER}",
]


def ensure_deployed(instance_ids: list[str]) -> None:
    logger.info("Vérification/déploiement de l'endpoint chaos5xx sur %s", instance_ids)
    common.run_on_all_instances(
        instance_ids,
        _DEPLOY_COMMANDS,
        comment="chaos-high-error-rate: deploiement endpoint (US 5.1)",
    )


def set_error_rate(instance_ids: list[str], rate: float) -> None:
    common.run_on_all_instances(
        instance_ids,
        [f"echo {rate} | sudo tee {_RATE_FILE} > /dev/null"],
        comment=f"chaos-high-error-rate: taux={rate}",
    )


def _generate_traffic(
    alb_dns: str, stop_event: threading.Event, requests_per_second: float
) -> dict[str, int]:
    url = f"http://{alb_dns}/cgi-bin/chaos5xx.py"
    counts = {"total": 0, "5xx": 0, "errors": 0}
    interval = 1.0 / max(requests_per_second, 0.1)
    while not stop_event.is_set():
        try:
            resp = requests.get(url, timeout=5)
            counts["total"] += 1
            if resp.status_code >= 500:
                counts["5xx"] += 1
        except requests.RequestException:
            counts["errors"] += 1
        time.sleep(interval)
    return counts


def run_once(
    run_index: int,
    instance_ids: list[str],
    alb_dns: str,
    error_rate: float = 0.5,
    requests_per_second: float = 5.0,
    max_duration_seconds: int = 420,
    alarm_timeout_seconds: int = 360,
    recovery_timeout_seconds: int = 300,
    dynamo_grace_seconds: int = 60,
) -> common.ScenarioResult:
    ensure_deployed(instance_ids)

    logger.info("[run %d] Vérification de l'état initial de l'alarme 5xx", run_index)
    state = common.get_alarm_state(common.ALARM_HIGH_ERROR_RATE)
    if state != "OK":
        logger.warning(
            "[run %d] Alarme pas en OK (%s) — remise à zéro préventive",
            run_index,
            state,
        )
        set_error_rate(instance_ids, 0.0)
        common.wait_for_alarm_state(
            common.ALARM_HIGH_ERROR_RATE, {"OK"}, timeout_seconds=300
        )

    logger.info(
        "[run %d] Injection de %.0f%% d'erreurs, trafic %.1f req/s vers %s",
        run_index,
        error_rate * 100,
        requests_per_second,
        alb_dns,
    )
    set_error_rate(instance_ids, error_rate)

    # FIX : capture des compteurs réels du thread de trafic (avant, le retour
    # de _generate_traffic était silencieusement perdu, empêchant tout
    # diagnostic du type "0 requêtes envoyées" ou "trafic OK mais 0% de 5xx").
    traffic_result: list[dict] = []
    stop_event = threading.Event()
    traffic_thread = threading.Thread(
        target=lambda: traffic_result.append(
            _generate_traffic(alb_dns, stop_event, requests_per_second)
        ),
        daemon=True,
    )
    t0 = time.monotonic()
    traffic_thread.start()

    triggered, alarm_time = common.wait_for_alarm_state(
        common.ALARM_HIGH_ERROR_RATE,
        {"ALARM"},
        timeout_seconds=alarm_timeout_seconds,
    )

    stop_event.set()
    traffic_thread.join(timeout=10)

    counts = (
        traffic_result[0] if traffic_result else {"total": 0, "5xx": 0, "errors": 0}
    )
    logger.info(
        "[run %d] Trafic généré : total=%d 5xx=%d erreurs_connexion=%d",
        run_index,
        counts["total"],
        counts["5xx"],
        counts["errors"],
    )

    incident_id = None
    notes = ""
    if not triggered:
        if counts["total"] == 0:
            notes = "Alarme non déclenchée : aucune requête n'a atteint l'ALB"
        elif counts["5xx"] == 0:
            notes = (
                f"Alarme non déclenchée : {counts['total']} requêtes envoyées "
                f"mais 0 en 5xx (endpoint chaos probablement mal configuré)"
            )
        else:
            notes = f"Alarme non déclenchée après {alarm_timeout_seconds}s ({counts['5xx']}/{counts['total']} en 5xx)"
        logger.error("[run %d] %s", run_index, notes)
    else:
        logger.info(
            "[run %d] ALARM détectée après %.0fs", run_index, time.monotonic() - t0
        )
        time.sleep(dynamo_grace_seconds)
        epoch = int(alarm_time.timestamp())
        incident_id = common.find_incident_since(epoch)
        if not incident_id:
            notes = "Alarme déclenchée mais aucun incident trouvé dans agent_decisions"
            logger.warning("[run %d] %s", run_index, notes)

    logger.info("[run %d] Arrêt de l'injection d'erreurs", run_index)
    set_error_rate(instance_ids, 0.0)

    recovered, recovery_time = common.wait_for_alarm_state(
        common.ALARM_HIGH_ERROR_RATE,
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
        description="Chaos High Error Rate — run unique (US 5.1)"
    )
    parser.add_argument(
        "--rate", type=float, default=0.5, help="Taux d'erreur 5xx injecté (0-1)"
    )
    parser.add_argument(
        "--rps", type=float, default=5.0, help="Requêtes par seconde générées"
    )
    parser.add_argument(
        "--alb-dns",
        type=str,
        default=None,
        help="DNS name de l'ALB (sinon résolu via boto3)",
    )
    args = parser.parse_args()

    instance_ids = common.resolve_instance_ids()
    alb_dns = args.alb_dns or common.resolve_alb_dns()
    result = run_once(
        1, instance_ids, alb_dns, error_rate=args.rate, requests_per_second=args.rps
    )
    common.append_csv(common.results_csv_path(SCENARIO), result.as_row())
    logger.info("Résultat : %s", result)


if __name__ == "__main__":
    main()
