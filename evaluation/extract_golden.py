import json
from collections import defaultdict
from datetime import UTC, datetime

import boto3

TABLE_NAME = "agent_decisions"
GOLDEN_PATH = "golden_dataset.json"

REQUIRED_NODES = {"Diagnostic", "Decision", "Communication"}
TERMINAL_DECISION_STATUSES = {
    "EXECUTED",
    "AUTO_REMEDIATED",
    "REFUSED_BY_WHITELIST",
    "DUPLICATE_ACTION_SKIPPED",
    "REJECTED_BY_HUMAN",
    "VALIDATION_TIMEOUT_ACTION_CANCELLED",
    "VALIDATION_STALE_ACTION_SKIPPED",
    "LOW_CONFIDENCE_SKIPPED",
    "REMEDIATION_UNAVAILABLE",
}
NB_INCIDENTS_CIBLE = 5


def _latest_decision_row(rows):
    decision_rows = [r for r in rows if r.get("node_name") == "Decision"]
    if not decision_rows:
        return None
    return max(decision_rows, key=lambda r: str(r.get("node_timestamp", "")))


def _check_required_nodes(nodes: set[str]) -> str | None:
    if not REQUIRED_NODES.issubset(nodes):
        return f"nodes manquants: {REQUIRED_NODES - nodes}"
    return None


def _check_decision_status(last_decision: dict) -> list[str]:
    raisons = []
    status = last_decision.get("decision_status")
    if status not in TERMINAL_DECISION_STATUSES:
        raisons.append(
            f"decision_status non terminal: {status!r} "
            "(incident probablement resté bloqué — ex. jamais repris après "
            "AWAITING_HUMAN_VALIDATION, cf. bug resume_handler)"
        )
    return raisons


def _check_low_confidence_without_judge_disagreement(
    last_decision: dict, rows: list[dict]
) -> str | None:
    status = last_decision.get("decision_status")
    try:
        confidence = float(last_decision.get("confidence", "0"))
    except (TypeError, ValueError):
        confidence = None

    if status != "EXECUTED" or confidence is None or confidence >= 85:
        return None

    judge_rows = [r for r in rows if r.get("node_name") == "Judge"]
    a_desaccord_justifiant = any(
        r.get("judge_verdict") == "incoherent" for r in judge_rows
    )
    if a_desaccord_justifiant:
        return None
    return (
        f"EXECUTED à confidence={confidence}% (<85%) sans désaccord "
        "juge documenté — anomalie connue, cf. rapport de validation"
    )


def _check_write_spread(rows: list[dict]) -> str | None:
    timestamps = [r.get("timestamp") for r in rows if r.get("timestamp")]
    try:
        ts_floats = [float(t) for t in timestamps]
    except (TypeError, ValueError):
        return None
    if ts_floats and (max(ts_floats) - min(ts_floats)) > 3600:
        return "étalement > 1h entre premier et dernier write (suspect)"
    return None


def check_incident_health(rows):
    raisons = []
    nodes = {r.get("node_name") for r in rows if r.get("node_name")}

    missing_nodes_reason = _check_required_nodes(nodes)
    if missing_nodes_reason:
        raisons.append(missing_nodes_reason)

    last_decision = _latest_decision_row(rows)
    if last_decision is None:
        raisons.append("aucune row Decision trouvée")
    else:
        raisons.extend(_check_decision_status(last_decision))
        confidence_reason = _check_low_confidence_without_judge_disagreement(
            last_decision, rows
        )
        if confidence_reason:
            raisons.append(confidence_reason)

    spread_reason = _check_write_spread(rows)
    if spread_reason:
        raisons.append(spread_reason)

    return (len(raisons) == 0, raisons)


def _scan_all_incidents(table):
    print(" Scan de la table DynamoDB...")
    items = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    print(f" {len(items)} lignes brutes récupérées.")

    groups = defaultdict(list)
    for item in items:
        iid = item.get("incident_id")
        if iid:
            groups[iid].append(item)
    print(f" {len(groups)} incidents uniques trouvés.")
    return groups


def _split_clean_and_dirty(groups):
    propres, sales = [], []
    for iid, rows in groups.items():
        ok, raisons = check_incident_health(rows)
        max_ts = max(
            [float(r.get("timestamp", 0)) for r in rows if r.get("timestamp")],
            default=0,
        )
        entry = {"iid": iid, "rows": rows, "max_ts": max_ts}
        if ok:
            propres.append(entry)
        else:
            sales.append({**entry, "raisons": raisons})

    print(f" {len(propres)} incidents propres (cohérents de bout en bout).")
    print(f" {len(sales)} incidents écartés :")
    for s in sorted(sales, key=lambda x: -x["max_ts"])[:20]:
        print(f"   - {s['iid']}: {'; '.join(s['raisons'])}")
    return propres


def _status_of(entry):
    d = _latest_decision_row(entry["rows"])
    return d.get("decision_status") if d else "UNKNOWN"


def _select_success_examples(entries_sorted):
    """Priorise jusqu'à 2 incidents avec un statut de succès
    (EXECUTED/AUTO_REMEDIATED) pour garantir que le dashboard peut montrer
    au moins un exemple de remédiation automatique réussie."""
    SUCCESS_STATUSES = {"EXECUTED", "AUTO_REMEDIATED"}
    succes = [e for e in entries_sorted if _status_of(e) in SUCCESS_STATUSES]
    if not succes:
        print(
            "  ATTENTION : aucun incident propre avec statut EXECUTED/AUTO_REMEDIATED "
            "trouvé parmi les incidents cohérents. Le dashboard ne pourra pas montrer "
            "de succès de remédiation automatique tant qu'un tel incident n'existe pas "
            "en base — à investiguer avant la démo, pas juste un problème de sélection."
        )
    return succes[:2]


def _add_new_status_entries(entries_sorted, selection, statuts_vus, target):
    """Complète `selection` avec un statut distinct par entrée, jusqu'à
    `target`. Extrait de _select_golden_entries() pour réduire sa
    complexité cognitive."""
    for entry in entries_sorted:
        if entry in selection:
            continue
        st = _status_of(entry)
        if st not in statuts_vus:
            selection.append(entry)
            statuts_vus.add(st)
        if len(selection) >= target:
            break


def _fill_remaining_entries(entries_sorted, selection, target):
    """Complète `selection` avec n'importe quelle entrée restante si la
    diversité de statuts n'a pas suffi à atteindre `target`."""
    for entry in entries_sorted:
        if entry not in selection:
            selection.append(entry)
        if len(selection) >= target:
            break


def _select_golden_entries(propres):
    """Sélectionne un échantillon varié : d'abord des succès, puis un
    statut distinct par entrée pour maximiser la diversité, puis on
    complète jusqu'à NB_INCIDENTS_CIBLE si besoin."""
    entries_sorted = sorted(propres, key=lambda x: -x["max_ts"])

    selection = _select_success_examples(entries_sorted)
    statuts_vus = {_status_of(e) for e in selection}

    _add_new_status_entries(entries_sorted, selection, statuts_vus, NB_INCIDENTS_CIBLE)

    if len(selection) < NB_INCIDENTS_CIBLE:
        _fill_remaining_entries(entries_sorted, selection, NB_INCIDENTS_CIBLE)

    return entries_sorted, selection


def _write_golden_dataset(selection):
    raw_items_to_save = []
    for entry in selection:
        raw_items_to_save.extend(entry["rows"])

    print(
        f"\n Écriture de {len(raw_items_to_save)} lignes ({len(selection)} incidents) dans {GOLDEN_PATH}"
    )
    with open(GOLDEN_PATH, "w", encoding="utf-8") as f:
        json.dump(raw_items_to_save, f, indent=2, default=str)

    print(
        f" {GOLDEN_PATH} mis à jour avec {len(selection)} incidents propres et variés :"
    )
    for entry in selection:
        st = _status_of(entry)
        alarm = next(
            (r.get("alarm_type") for r in entry["rows"] if r.get("alarm_type")),
            "?",
        )
        ts = entry["max_ts"]
        print(
            f"   - {entry['iid']} | {alarm} | {st} | "
            f"{datetime.fromtimestamp(ts, tz=UTC).isoformat()}"
        )


def main():
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    groups = _scan_all_incidents(table)
    propres = _split_clean_and_dirty(groups)

    if not propres:
        print(
            "Aucun incident propre trouvé. Le golden_dataset.json ne sera PAS mis à jour "
            "(mieux vaut garder l'ancien jeu de données que d'écrire un fichier vide)."
        )
        return

    _, selection = _select_golden_entries(propres)
    _write_golden_dataset(selection)


if __name__ == "__main__":
    main()
