"""
Tests complémentaires — agent/groundedness.py

test_groundedness.py couvre déjà : step ancré (overlap >= seuil), step
halluciné (overlap < seuil), et reasoning_steps vide. Ce fichier cible les
deux branches encore non couvertes (91.3% -> 2 lignes rouges) :

  1. `if not evidence_tokens: return 0.0` — aucune preuve disponible du
     tout (logs bruts ET contexte d'alarme vides).
  2. `if not step_tokens: continue` — un reasoning_step qui ne contient
     aucun token "significatif" au sens de _WORD_RE (mots de moins de
     3 caractères), donc ignoré plutôt que de fausser le score.
"""

from __future__ import annotations

from agent.groundedness import compute_groundedness_score
from agent.models import RCAResult


def _rca(steps):
    return RCAResult(
        diagnosis="test",
        confidence=90,
        suggested_action="ScaleOut",
        reasoning_steps=steps,
    )


def test_no_evidence_at_all_returns_zero():
    """logs bruts ET contexte d'alarme vides -> aucune preuve disponible,
    le score doit être 0.0 sans même tenter de comparer les steps."""
    result = _rca(["Un raisonnement quelconque, non vérifiable ici"])
    score = compute_groundedness_score(result, raw_logs_text="", alarm_context_text="")
    assert score == 0.0


def test_alarm_context_alone_can_ground_a_step():
    """Contrôle croisé de la branche précédente : dès qu'une des deux
    sources de preuve (ici le contexte d'alarme seul, logs vides) contient
    de quoi ancrer le step, le score n'est plus forcé à 0.0."""
    result = _rca(["Le CPU a dépassé le seuil critique configuré"])
    score = compute_groundedness_score(
        result,
        raw_logs_text="",
        alarm_context_text="Le CPU a dépassé le seuil critique configuré",
    )
    assert score == 1.0


def test_step_without_significant_tokens_is_skipped_not_grounded():
    """Un step composé uniquement de mots de moins de 3 caractères (donc
    hors du vocabulaire de _WORD_RE) doit être ignoré (continue) plutôt
    que de compter comme non-ancré : aucune division par zéro ni erreur
    ne doit se produire, et le score reste basé sur len(steps)."""
    result = _rca(["ok ci la"])
    score = compute_groundedness_score(
        result, raw_logs_text="kernel: high load average detected"
    )
    assert score == 0.0


def test_score_is_rounded_to_two_decimals():
    """1 step ancré sur 3 -> 0.333... doit être arrondi à 0.33."""
    logs = "kernel: high sustained load average detected on nginx process"
    result = _rca(
        [
            "Le log mentionne un load average élevé sur le process nginx",
            "Le disque est plein selon les métriques CloudWatch",
            "La mémoire swap est saturée depuis 10 minutes",
        ]
    )
    score = compute_groundedness_score(result, logs)
    assert score == round(1 / 3, 2)
