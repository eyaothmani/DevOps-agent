"""
Test LOCAL, gratuit, sans AWS — valide uniquement la logique de
vérification de signature Slack (_verify_slack_signature), en simulant
un vrai appel Slack signé avec le VRAI signing secret.

Usage :
    python test_slack_signature_local.py <SLACK_SIGNING_SECRET>

Le secret est à coller en argument (celui de Slack > Basic Information >
App Credentials > Signing Secret) — jamais en dur dans ce fichier.
"""

import hashlib
import hmac
import sys
import time


def build_fake_slack_request(signing_secret: str) -> tuple[dict, str]:
    """Construit un faux payload Slack, signé exactement comme le ferait Slack."""
    timestamp = str(int(time.time()))
    raw_body = "payload=%7B%22fake%22%3A%22body%22%7D"  # payload=... URL-encodé minimal

    basestring = f"v0:{timestamp}:{raw_body}"
    computed_signature = (
        "v0="
        + hmac.new(
            signing_secret.encode(), basestring.encode(), hashlib.sha256
        ).hexdigest()
    )

    # Simule EXACTEMENT ce que renvoie API Gateway HTTP API (payload format
    # 2.0) : tous les en-têtes en MINUSCULES.
    headers = {
        "x-slack-request-timestamp": timestamp,
        "x-slack-signature": computed_signature,
        "content-type": "application/x-www-form-urlencoded",
    }
    return headers, raw_body


def verify_slack_signature_reference(
    headers: dict, raw_body: str, signing_secret: str
) -> bool:
    """Copie EXACTE de la logique corrigée dans resume_handler.py, pour
    tester en isolation sans dépendre d'agent.config (pas besoin d'env AWS)."""
    headers_lower = {k.lower(): v for k, v in headers.items()}
    timestamp = headers_lower.get("x-slack-request-timestamp", "0")
    slack_signature = headers_lower.get("x-slack-signature", "")

    try:
        if abs(time.time() - int(timestamp)) > 60 * 5:
            print(f"REJET : timestamp hors fenêtre (timestamp={timestamp})")
            return False
    except ValueError:
        print(f"REJET : timestamp invalide reçu={timestamp!r}")
        return False

    basestring = f"v0:{timestamp}:{raw_body}"
    computed = (
        "v0="
        + hmac.new(
            signing_secret.encode(), basestring.encode(), hashlib.sha256
        ).hexdigest()
    )
    match = hmac.compare_digest(computed, slack_signature)
    if not match:
        print(
            f"REJET : signature mismatch. computed={computed[:20]}... received={slack_signature[:20]}..."
        )
    return match


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage : python test_slack_signature_local.py <SLACK_SIGNING_SECRET>")
        sys.exit(1)

    secret = sys.argv[1]

    print("=" * 60)
    print("TEST 1 — Signature VALIDE (doit passer)")
    print("=" * 60)
    headers, raw_body = build_fake_slack_request(secret)
    result = verify_slack_signature_reference(headers, raw_body, secret)
    print(
        f"Résultat : {'✅ ACCEPTÉ (correct)' if result else '❌ REJETÉ (BUG — devrait être accepté)'}"
    )

    print()
    print("=" * 60)
    print("TEST 2 — Signature INVALIDE (doit être rejetée)")
    print("=" * 60)
    headers_bad, raw_body_bad = build_fake_slack_request("mauvais_secret_pour_test")
    result_bad = verify_slack_signature_reference(headers_bad, raw_body_bad, secret)
    print(
        f"Résultat : {'❌ ACCEPTÉ (BUG — devrait être rejeté)' if result_bad else '✅ REJETÉ (correct)'}"
    )

    print()
    print("=" * 60)
    print(
        "TEST 3 — Headers en MAJUSCULES façon ancien code (doit quand même passer avec le fix)"
    )
    print("=" * 60)
    headers_upper, raw_body_upper = build_fake_slack_request(secret)
    headers_upper = {k.upper(): v for k, v in headers_upper.items()}
    result_upper = verify_slack_signature_reference(
        headers_upper, raw_body_upper, secret
    )
    print(
        f"Résultat : {'✅ ACCEPTÉ (correct — fix casse fonctionne)' if result_upper else '❌ REJETÉ (BUG — fix casse ne fonctionne pas)'}"
    )
