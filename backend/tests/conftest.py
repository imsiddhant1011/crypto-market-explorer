"""
Shared pytest fixtures.

The tests never touch the imported market data: they run against a **separate
database** (``TEST_DATABASE_URL``, default ``crypto_test``) that is created when
the PostgreSQL container initialises its volume.

Run them with:

    docker compose exec backend pytest -v

or, from the repository root against a database reachable on localhost:

    docker compose exec backend pytest -v          # recommended
    cd backend && TEST_DATABASE_URL=... pytest -v   # if you installed the requirements locally
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal

import psycopg
import pytest
from psycopg.rows import dict_row

# The application reads these environment variables when it creates its
# connection pool, so they must be set before `app` is imported. conftest.py is
# loaded before the test modules, which is why this happens here.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://crypto:crypto_dev_password@localhost:5432/crypto_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app import database  # noqa: E402  (import after the environment is prepared)

# An arbitrary, fixed, epoch-aligned UTC minute used by the tests.
BASE_TIME = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

INSERT_ROW_SQL = """\
INSERT INTO candles (symbol, open_time, open, high, low, close, volume)
VALUES (%(symbol)s, %(open_time)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s)"""


def minute(
    open_time: datetime,
    open_: str = "100",
    high: str = "110",
    low: str = "90",
    close: str = "105",
    volume: str = "1",
) -> dict:
    """Build one candle row as a dict (numbers are strings -> exact NUMERIC)."""
    return {
        "open_time": open_time,
        "open": Decimal(open_),
        "high": Decimal(high),
        "low": Decimal(low),
        "close": Decimal(close),
        "volume": Decimal(volume),
    }


def insert_candle_rows(conn: psycopg.Connection, symbol: str, rows: list[dict]) -> None:
    """Insert candle rows and commit, so the API (another connection) sees them."""
    with conn.cursor() as cursor:
        cursor.executemany(
            INSERT_ROW_SQL,
            [{"symbol": symbol, **row} for row in rows],
        )
    conn.commit()


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """Create the schema in the test database once per test session."""
    schema_path = database.schema_file()
    if not schema_path.exists():
        pytest.exit(f"Schema file not found: {schema_path}", returncode=1)

    schema_sql = schema_path.read_text(encoding="utf-8")
    try:
        with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
            conn.execute(schema_sql)
    except psycopg.OperationalError as exc:
        pytest.exit(
            "Cannot reach the test database.\n"
            f"  TEST_DATABASE_URL={database.redact(TEST_DATABASE_URL)}\n"
            "  Start it with: docker compose up -d db\n"
            f"  ({exc.__class__.__name__}: {str(exc).splitlines()[0]})",
            returncode=1,
        )

    yield
    database.close_pool()


@pytest.fixture(autouse=True)
def clean_candles(test_database):
    """Every test starts with an empty candles table (the symbols seed stays)."""
    # Rebuild the pool so a test that changed DATABASE_URL cannot leak into the
    # next one; the pool is created lazily from the environment.
    database.close_pool()
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute("DELETE FROM candles;")
    yield


@pytest.fixture
def db_connection():
    """A connection to the test database with dict rows."""
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        yield conn


@pytest.fixture
def insert_candles(db_connection):
    """insert_candles(symbol, rows) -> insert candle rows and commit them."""

    def _insert(symbol: str, rows: list[dict]) -> None:
        insert_candle_rows(db_connection, symbol, rows)

    return _insert


@pytest.fixture(scope="session")
def client():
    """A FastAPI test client (the lifespan opens/closes the connection pool)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
