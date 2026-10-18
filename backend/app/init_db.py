"""
Create the database schema and seed the symbols table.

Run as a module from the backend directory (this is what the container does):

    python -m app.init_db

The script waits for PostgreSQL to accept connections first, then executes
`database/init.sql`. Both steps are idempotent, so running it again - or running
it while the database is already in use - is safe.
"""

from __future__ import annotations

import sys
import time

import psycopg

from . import database


def wait_for_database(url: str, attempts: int = 30, delay_seconds: float = 2.0) -> None:
    """Block until PostgreSQL accepts a connection (readiness check)."""
    for attempt in range(1, attempts + 1):
        try:
            with psycopg.connect(url, connect_timeout=3):
                print(f"[init_db] PostgreSQL is ready (attempt {attempt}).")
                return
        except psycopg.OperationalError as exc:
            reason = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
            print(f"[init_db] waiting for PostgreSQL ({attempt}/{attempts}): {reason}")
            time.sleep(delay_seconds)
    raise SystemExit("[init_db] PostgreSQL did not become available - giving up.")


def apply_schema() -> None:
    """Wait for the database, then apply database/init.sql."""
    url = database.database_url()
    schema_path = database.schema_file()

    if not schema_path.exists():
        raise SystemExit(f"[init_db] schema file not found: {schema_path}")

    print(f"[init_db] database : {database.redact(url)}")
    print(f"[init_db] schema   : {schema_path}")
    wait_for_database(url)

    schema_sql = schema_path.read_text(encoding="utf-8")
    # A single execute() call can run several statements when it has no
    # parameters, which is exactly the case for this schema file.
    with psycopg.connect(url) as conn:
        with conn.cursor() as cursor:
            cursor.execute(schema_sql)
            cursor.execute(
                "SELECT symbol, display_name FROM symbols ORDER BY symbol"
            )
            symbols = cursor.fetchall()

    print(f"[init_db] schema applied. Seeded symbols: {symbols}")
    print("[init_db] done.")


def main() -> int:
    apply_schema()
    return 0


if __name__ == "__main__":
    sys.exit(main())
