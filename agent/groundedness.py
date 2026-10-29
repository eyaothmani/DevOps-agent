from __future__ import annotations

import re

from agent.models import RCAResult

_WORD_RE = re.compile(r"[a-zA-Z0-9_\-\.]{3,}")
_MIN_OVERLAP_RATIO = 0.4  # un reasoning_step est jugé "ancré" si ≥40% de ses
# tokens significatifs apparaissent dans les logs bruts


def _tokenize(text: str) -> set[str]:
    return {tok.lower() for tok in _WORD_RE.findall(text)}


def compute_groundedness_score(
    rca_result: RCAResult,
    raw_logs_text: str,
    alarm_context_text: str = "",
) -> float:
    """Proportion des reasoning_steps dont le contenu recoupe effectivement
    les preuves fournies au modèle — logs bruts ET contexte d'alarme
    (alarm_context_text : nom, raison, métrique, seuil), pour ne pas
    pénaliser à tort un diagnostic correctement ancré sur la valeur
    métrique de l'alarme plutôt que sur les logs applicatifs (cas typique
    des alarmes purement métriques comme CPU High).

    Retourne un float entre 0.0 et 1.0. 0.0 si reasoning_steps est vide ou
    si aucune preuve n'est disponible.
    """
    steps = rca_result.reasoning_steps
    if not steps:
        return 0.0

    evidence_tokens = _tokenize(raw_logs_text) | _tokenize(alarm_context_text)
    if not evidence_tokens:
        return 0.0

    grounded = 0
    for step in steps:
        step_tokens = _tokenize(step)
        if not step_tokens:
            continue
        overlap = step_tokens & evidence_tokens
        if len(overlap) / len(step_tokens) >= _MIN_OVERLAP_RATIO:
            grounded += 1

    return round(grounded / len(steps), 2)
