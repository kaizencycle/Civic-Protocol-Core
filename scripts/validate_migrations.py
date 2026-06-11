#!/usr/bin/env python3
"""Validate SQL migrations against a scratch database.

The production migrations are Postgres-oriented, while this repository's local
CI does not provision Postgres. This validator translates the narrow syntax used
by the current migration set into SQLite-compatible SQL so ordering and basic
DDL drift are still caught before deploy.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


def _sqlite_compatible(sql: str) -> str:
    translated = sql
    replacements = {
        "TIMESTAMPTZ": "TEXT",
        "JSONB": "TEXT",
        "BOOLEAN": "INTEGER",
        "NOW()": "CURRENT_TIMESTAMP",
        "DEFAULT FALSE": "DEFAULT 0",
        "DEFAULT TRUE": "DEFAULT 1",
    }
    for old, new in replacements.items():
        translated = translated.replace(old, new)
    translated = re.sub(
        r"ADD COLUMN IF NOT EXISTS\s+",
        "ADD COLUMN ",
        translated,
        flags=re.IGNORECASE,
    )
    return translated


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def validate_migrations() -> None:
    files = migration_files()
    if not files:
        raise RuntimeError("No migration files found")

    with sqlite3.connect(":memory:") as conn:
        for path in files:
            sql = _sqlite_compatible(path.read_text(encoding="utf-8"))
            conn.executescript(sql)


def main() -> int:
    validate_migrations()
    print(f"Validated {len(migration_files())} migration files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
