"""Journalisation locale des opérations destructives/exports (audit trail)."""

from __future__ import annotations

import getpass
import os
from datetime import UTC, datetime

from . import config


def audit(action: str, details: str) -> None:
    """Écrit une trace d'audit locale."""
    who = os.getenv("USER") or os.getenv("USERNAME") or getpass.getuser()

    line = (
        f"{datetime.now(UTC).isoformat()} | "
        f"user={who} | "
        f"table={config.TABLE_NAME} | "
        f"{action} | "
        f"{details}\n"
    )

    try:
        with config.AUDIT_LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(line)
    except OSError as exc:
        config.logger.warning(
            "Impossible d'écrire le log d'audit (%s) : %s", config.AUDIT_LOG_PATH, exc
        )

    config.logger.info(line.strip())