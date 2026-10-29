"""Public API for DynamoDB table management.

This module keeps the public API backward-compatible while the
implementation is split into dedicated modules.
"""

from pathlib import Path

from . import config
from .audit_trail import audit
from .commands import (
    cmd_export_golden,
    cmd_inspect,
    cmd_inspect_incident,
    cmd_keep_latest,
    cmd_list_values,
    cmd_purge,
    cmd_schema,
)
from .commands.delete_rows import (
    _confirm_major_deletion,
    _confirm_normal_deletion,
    confirm_destructive,
    delete_one_row,
)
from .dynamo import get_table, key_from_item
from .transform import redact_sensitive
from .validators import positive_int, safe_output_path, validate_table_name

# ---------------------------------------------------------------------------
# Backward-compatible configuration names
# ---------------------------------------------------------------------------

_OUTPUT_ROOT = config.OUTPUT_ROOT
AUDIT_LOG_PATH = config.AUDIT_LOG_PATH


# ---------------------------------------------------------------------------
# Backward-compatible validator wrappers
# ---------------------------------------------------------------------------

def _safe_output_path(raw_path: Path) -> Path:
    """Validate that the output path stays under the configured root."""
    resolved = raw_path.expanduser().resolve()

    try:
        resolved.relative_to(_OUTPUT_ROOT)
    except ValueError as exc:
        raise SystemExit(
            f"--output doit rester sous {_OUTPUT_ROOT} "
            f"(reçu : {resolved})"
        ) from exc

    return resolved


_validate_table_name = validate_table_name
_positive_int = positive_int


# ---------------------------------------------------------------------------
# Backward-compatible audit wrapper
# ---------------------------------------------------------------------------

def _audit(action: str, details: str) -> None:
    """Write an audit entry using the monkeypatchable legacy path."""
    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(f"{action} | {details}\n")


# ---------------------------------------------------------------------------
# Backward-compatible destructive command names
# ---------------------------------------------------------------------------

_confirm_destructive = confirm_destructive
_delete_one_row = delete_one_row


# ---------------------------------------------------------------------------
# CLI compatibility
# ---------------------------------------------------------------------------

from .cli import (
    _build_parser,
    _has_command,
    _run_commands,
    _run_destructive_commands,
    _run_export_command,
    _run_read_commands,
)


def main() -> int:
    """Backward-compatible CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    if not _has_command(args):
        parser.print_help()
        return 1

    try:
        table = get_table()
    except ValueError:
        return 2

    _run_commands(args, table)
    return 0


__all__ = [
    "_audit",
    "_confirm_destructive",
    "_confirm_major_deletion",
    "_confirm_normal_deletion",
    "_delete_one_row",
    "_positive_int",
    "_run_destructive_commands",
    "_run_export_command",
    "_run_read_commands",
    "_safe_output_path",
    "_validate_table_name",
    "audit",
    "cmd_export_golden",
    "cmd_inspect",
    "cmd_inspect_incident",
    "cmd_keep_latest",
    "cmd_list_values",
    "cmd_purge",
    "cmd_schema",
    "get_table",
    "key_from_item",
    "main",
    "redact_sensitive",
    "safe_output_path",
]