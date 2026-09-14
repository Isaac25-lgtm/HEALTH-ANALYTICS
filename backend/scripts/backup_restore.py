"""SQLite backup and restore helper.

This script copies a SQLite database file. It refuses PostgreSQL URLs so a
shared cluster is never used as a dump target. Production PostgreSQL backup
uses the host's pg_dump/pg_restore process documented in DEPLOYMENT.md.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def refuse_non_sqlite(url_or_path: str) -> None:
    lowered = url_or_path.lower()
    if lowered.startswith("postgresql") or lowered.startswith("postgres"):
        raise ValueError(
            "SQLite-only helper. Use pg_dump for PostgreSQL; do not dump a shared cluster from this script."
        )


def backup_sqlite(source: Path, destination: Path) -> Path:
    refuse_non_sqlite(str(source))
    if not source.exists():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def restore_sqlite(backup: Path, destination: Path) -> Path:
    refuse_non_sqlite(str(destination))
    if not backup.exists():
        raise FileNotFoundError(backup)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, destination)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy a SQLite HPIP database. Refuses PostgreSQL URLs.")
    parser.add_argument("action", choices=("backup", "restore"))
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    refuse_non_sqlite(args.source)
    refuse_non_sqlite(args.destination)
    if args.action == "backup":
        backup_sqlite(Path(args.source), Path(args.destination))
    else:
        restore_sqlite(Path(args.source), Path(args.destination))


if __name__ == "__main__":
    main()
