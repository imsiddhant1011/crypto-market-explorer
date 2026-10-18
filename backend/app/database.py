"""
Database connections and file locations.

The API uses a small psycopg connection pool. The pool is created on first use
(not at import time) so that the module can be imported - by tests, for example -
without a running database.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

# Development default. docker-compose.yml passes DATABASE_URL explicitly and
# .env.example documents how to change it.
DEFAULT_DATABASE_URL = (
    "postgresql://crypto:crypto_dev_password@localhost:5432/crypto_market_explorer"
)

_pool: ConnectionPool | None = None


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def pool_timeout() -> float:
    """Seconds a request waits for a free pooled connection before failing."""
    return float(os.environ.get("DB_POOL_TIMEOUT", "5"))


def project_root() -> Path:
    """Repository root: the directory containing docker-compose.yml."""
    return Path(__file__).resolve().parents[2]


def schema_file() -> Path:
    """SQL file that creates the schema (env SCHEMA_FILE, default database/init.sql)."""
    return Path(os.environ.get("SCHEMA_FILE", project_root() / "database" / "init.sql"))


def data_dir() -> Path:
    """Directory holding the historical CSV files (env DATA_DIR, default data/)."""
    return Path(os.environ.get("DATA_DIR", project_root() / "data"))


def get_pool() -> ConnectionPool:
    """Return the connection pool, creating (and opening) it on first use."""
    global _pool
    if _pool is None:
        logger.info("Creating database connection pool for %s", redact(database_url()))
        _pool = ConnectionPool(
            conninfo=database_url(),
            min_size=1,
            max_size=5,
            open=False,
            timeout=pool_timeout(),
            kwargs={"row_factory": dict_row, "connect_timeout": 5},
            name="crypto-market-explorer",
        )
    if _pool.closed:
        _pool.open(wait=False)
    return _pool


def open_pool() -> None:
    """
    Create the pool when the API starts, so connection problems show up in the
    logs immediately.

    `wait=False` keeps the API reachable even when PostgreSQL is down: the pool
    reconnects in the background and GET /api/health reports the problem instead
    of the container dying.
    """
    get_pool()


def close_pool() -> None:
    """Close the pool and forget it (used on shutdown and by the tests)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    """
    Check out a pooled connection.

    The context manager commits on success and rolls back on error, so callers
    never have to manage transactions for the read-only queries of this project.
    """
    with get_pool().connection(timeout=pool_timeout()) as conn:
        yield conn


def redact(url: str) -> str:
    """Hide the password of a connection URL before logging it."""
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    credentials, host = parts.netloc.rsplit("@", 1)
    user = credentials.split(":", 1)[0]
    return urlunsplit(parts._replace(netloc=f"{user}:***@{host}"))
