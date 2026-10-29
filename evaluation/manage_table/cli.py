import argparse
import logging
from pathlib import Path
from typing import Any

from .commands import (
    cmd_export_golden,
    cmd_inspect,
    cmd_inspect_incident,
    cmd_keep_latest,
    cmd_list_values,
    cmd_purge,
    cmd_schema,
)
from .dynamo import get_table
from .validators import positive_int

logger = logging.getLogger("manage_table")


def _build_parser() -> argparse.ArgumentParser:
    """Construit le parser CLI."""
    parser = argparse.ArgumentParser(
        description="Gestion de la table DynamoDB agent_decisions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--schema", action="store_true")
    parser.add_argument(
        "--list-values",
        type=str,
        default=None,
        metavar="FIELD",
    )
    parser.add_argument(
        "--inspect-incident",
        type=str,
        default=None,
    )
    parser.add_argument("--purge", action="store_true")
    parser.add_argument(
        "--keep-after",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--keep-latest",
        type=positive_int,
        default=None,
        metavar="N",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--export-golden", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation/golden_dataset.json"),
    )
    parser.add_argument(
        "--reveal-sensitive",
        action="store_true",
        help=(
            "Désactive le masquage des champs sensibles "
            "(tokens, secrets, webhooks)."
        ),
    )

    return parser


def _has_command(args: argparse.Namespace) -> bool:
    """Vérifie si une commande CLI a été sélectionnée."""
    return any(
        (
            args.inspect,
            args.schema,
            args.list_values,
            args.inspect_incident,
            args.purge,
            args.keep_latest is not None,
            args.export_golden,
        )
    )


# Alias public — attendu par tests/unit/manage_table/test_cli.py (cli.has_command)
has_command = _has_command


def _run_read_commands(
    args: argparse.Namespace,
    table: Any,
) -> None:
    """Exécute les commandes de lecture."""
    if args.list_values:
        cmd_list_values(table, args.list_values)

    if args.schema:
        cmd_schema(table)

    if args.inspect:
        cmd_inspect(
            table,
            reveal_sensitive=args.reveal_sensitive,
        )

    if args.inspect_incident:
        cmd_inspect_incident(
            table,
            args.inspect_incident,
            reveal_sensitive=args.reveal_sensitive,
        )


def _run_destructive_commands(
    args: argparse.Namespace,
    table: Any,
) -> None:
    """Exécute les commandes destructives."""
    if args.purge:
        cmd_purge(
            table,
            keep_after=args.keep_after,
            dry_run=args.dry_run,
        )

    if args.keep_latest is not None:
        cmd_keep_latest(
            table,
            n=args.keep_latest,
            dry_run=args.dry_run,
        )


def _run_export_command(
    args: argparse.Namespace,
    table: Any,
) -> None:
    """Exécute la commande d'export."""
    if not args.export_golden:
        return

    cmd_export_golden(
        table,
        args.output,
        reveal_sensitive=args.reveal_sensitive,
    )


def _run_commands(
    args: argparse.Namespace,
    table: Any,
) -> None:
    """Dispatch centralisé des commandes CLI."""
    _run_read_commands(args, table)
    _run_destructive_commands(args, table)
    _run_export_command(args, table)


def main() -> int:
    """Point d'entrée CLI compatible avec l'ancienne API."""
    parser = _build_parser()
    args = parser.parse_args()

    if not _has_command(args):
        parser.print_help()
        return 1

    if getattr(args, "reveal_sensitive", False):
        logger.warning(
            "--reveal-sensitive activé : les champs sensibles "
            "(tokens, secrets, webhooks) ne seront PAS masqués dans la sortie."
        )

    try:
        table = get_table()
    except ValueError:
        return 2

    _run_commands(args, table)
    return 0