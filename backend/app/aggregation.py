"""
Window calculation and data retrieval for the candle endpoint.

The OHLCV aggregation itself is performed by PostgreSQL - see the SQL in
`queries.py`. This module only decides *which* rows to aggregate and turns the
rows that come back into JSON that the chart can use.

Timestamp convention
--------------------
Everything is UTC and the window is aligned to interval boundaries:

    window_end   = the first bucket boundary at or after "last stored minute + 1 minute"
    window_start = window_end - the requested range (24h or 7d)

Because 5, 15 and 30 minutes all divide 24 hours exactly, the window always
starts and ends on a bucket boundary. That is what lets the SQL use a plain
`HAVING count(*) = <bucket size>` completeness check: every bucket inside an
aligned window contains all of its source minutes or none of them.

The window is anchored on `max(open_time)` of the imported data, never on
`now()`, so a historical dataset is displayed correctly no matter when the
application is started.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import database, queries
from .queries import IntervalDefinition, RangeDefinition

UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class UnknownSymbolError(Exception):
    """Raised when a request asks for a symbol that is not in the symbols table."""

    def __init__(self, symbol: str, known_symbols: list[str]) -> None:
        known = ", ".join(known_symbols) if known_symbols else "none"
        super().__init__(f"Unknown symbol '{symbol}'. Supported symbols: {known}.")
        self.symbol = symbol
        self.known_symbols = known_symbols


# ---------------------------------------------------------------------------
# Window calculation (pure functions - easy to test without a database)
# ---------------------------------------------------------------------------


def ceil_to_bucket(moment: datetime, minutes: int) -> datetime:
    """Round a UTC timestamp up to the next bucket boundary."""
    moment = moment.astimezone(timezone.utc)
    step = timedelta(minutes=minutes)
    elapsed = moment - UNIX_EPOCH
    buckets = -(-elapsed // step)  # ceiling division: timedelta // timedelta -> int
    return UNIX_EPOCH + buckets * step


def align_window(
    last_open_time: datetime,
    interval: IntervalDefinition,
    requested_range: RangeDefinition,
) -> tuple[datetime, datetime]:
    """
    Return the inclusive start and exclusive end of the chart window.

    A 24-hour range contains exactly 288 five-minute, 96 fifteen-minute or
    48 thirty-minute candles.
    """
    window_end = ceil_to_bucket(last_open_time + timedelta(minutes=1), interval.minutes)
    window_start = window_end - requested_range.duration
    if (window_end - window_start) % timedelta(minutes=interval.minutes) != timedelta(0):
        raise ValueError("range must be a whole number of intervals")
    return window_start, window_end


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def list_symbols() -> list[dict]:
    """Trading pairs from the symbols table, ordered by symbol."""
    with database.connection() as conn, conn.cursor() as cursor:
        cursor.execute(queries.SYMBOLS_SQL)
        return [dict(row) for row in cursor.fetchall()]


def check_database() -> dict:
    """Small status report used by GET /api/health."""
    with database.connection() as conn, conn.cursor() as cursor:
        cursor.execute(queries.HEALTH_SQL)
        row = cursor.fetchone()
    return {
        "status": "ok",
        "database": "reachable",
        "symbols": row["symbol_count"],
        "candles": row["candle_count"],
        "latest_candle_utc": iso_timestamp(row["latest_candle"]),
    }


def build_candles_response(symbol: str, interval_name: str, range_name: str) -> dict:
    """
    Aggregate candles with SQL and build the JSON payload for GET /api/candles.

    `interval_name` and `range_name` must already be validated; they are used as
    dictionary keys (an allowlist lookup), never as SQL text.
    """
    interval = queries.INTERVALS[interval_name]
    requested_range = queries.RANGES[range_name]

    with database.connection() as conn, conn.cursor() as cursor:
        # Symbols are validated against the records in the database, not against
        # a list hard-coded here.
        cursor.execute(queries.SYMBOLS_SQL)
        symbols = {row["symbol"]: dict(row) for row in cursor.fetchall()}
        symbol_row = symbols.get(symbol)
        if symbol_row is None:
            raise UnknownSymbolError(symbol, sorted(symbols))

        cursor.execute(queries.DATASET_RANGE_SQL, {"symbol": symbol})
        dataset = cursor.fetchone()
        first_open_time = dataset["first_open_time"]
        last_open_time = dataset["last_open_time"]

        window_start: datetime | None = None
        window_end: datetime | None = None
        candles: list[dict] = []

        if last_open_time is not None:
            window_start, window_end = align_window(
                last_open_time, interval, requested_range
            )
            # The one and only aggregation query. Its text is the same string
            # that is shown in the educational panel of the frontend.
            cursor.execute(
                interval.sql,
                {
                    "symbol": symbol,
                    "window_start": window_start,
                    "window_end": window_end,
                },
            )
            candles = [serialize_candle(row) for row in cursor.fetchall()]

    return {
        "symbol": symbol_row["symbol"],
        "base_asset": symbol_row["base_asset"],
        "quote_asset": symbol_row["quote_asset"],
        "display_name": symbol_row["display_name"],
        "interval": interval.name,
        "interval_minutes": interval.minutes,
        "interval_seconds": interval.minutes * 60,
        "range": requested_range.name,
        "range_label": requested_range.label,
        "timezone": "UTC",
        "window_start": iso_timestamp(window_start),
        "window_end": iso_timestamp(window_end),
        "dataset_first_timestamp": iso_timestamp(first_open_time),
        "dataset_last_timestamp": iso_timestamp(last_open_time),
        "source_candles_per_bucket": interval.expected_candles,
        "candle_count": len(candles),
        "candles": candles,
        "education": {
            "title": interval.title,
            "sql": interval.sql,
            "parameters": {
                "symbol": symbol,
                "window_start": iso_timestamp(window_start),
                "window_end": iso_timestamp(window_end),
            },
            "explanation": interval.explanation,
            "ohlcv_rules": interval.ohlcv_rules,
            "completeness_rule": interval.completeness_rule,
            "concepts": interval.concepts,
        },
    }


def serialize_candle(row: dict) -> dict:
    """
    Convert one database row into the shape used by Lightweight Charts.

    `time` is Unix time in **seconds** (that is what Lightweight Charts expects).

    NUMERIC columns arrive as Python Decimal; they are converted to float for
    JSON because JavaScript numbers are the only type the chart can plot. A
    double keeps about 16 significant digits, far more than a price or volume
    needs, and the database itself still stores the exact NUMERIC value. No
    rounding is applied.
    """
    return {
        "time": int(row["bucket_start"].timestamp()),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]),
    }


def iso_timestamp(value: datetime | None) -> str | None:
    """Format a UTC timestamp as 2026-10-17T23:59:00Z (None stays None)."""
    if value is None:
        return None
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
