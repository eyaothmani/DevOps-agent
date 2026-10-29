#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AGENT_SRC = ROOT / "agent"
REQUIREMENTS = ROOT / "requirements-lambda.txt"
PACKAGE_DIR = ROOT / "agent" / "package"

EXCLUDE_DIR_NAMES = {"package", "__pycache__", ".pytest_cache"}


def clean_package_dir() -> None:
    if PACKAGE_DIR.exists():
        shutil.rmtree(PACKAGE_DIR)
    PACKAGE_DIR.mkdir(parents=True)


def install_dependencies() -> None:
    if not REQUIREMENTS.exists():
        print(f"ERREUR : {REQUIREMENTS} introuvable.", file=sys.stderr)
        sys.exit(1)

    cmd = [
        sys.executable, "-m", "pip", "install",
        "-r", str(REQUIREMENTS),
        "--target", str(PACKAGE_DIR),
        "--platform", "manylinux2014_x86_64",
        "--implementation", "cp",
        "--python-version", "3.11",
        "--only-binary=:all:",
        "--upgrade",
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("ERREUR : échec de pip install.", file=sys.stderr)
        sys.exit(result.returncode)


def copy_agent_source() -> None:
    dest = PACKAGE_DIR / "agent"

    def ignore(dir_path, names):
        ignored = {n for n in names if n in EXCLUDE_DIR_NAMES}
        ignored |= {n for n in names if n.endswith(".pyc")}
        return ignored

    shutil.copytree(AGENT_SRC, dest, ignore=ignore)


def main() -> None:
    print(f"[build_lambda_package] Nettoyage de {PACKAGE_DIR} ...")
    clean_package_dir()
    print("[build_lambda_package] Installation des dependances ...")
    install_dependencies()
    print(f"[build_lambda_package] Copie de {AGENT_SRC} -> {PACKAGE_DIR / 'agent'} ...")
    copy_agent_source()
    print("[build_lambda_package] Termine.")


if __name__ == "__main__":
    main()
