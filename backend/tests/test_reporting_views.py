"""
Tests for the `reporting` views used by the Power BI dashboard.

Power BI imports these views directly, so they must expose the same candles the
API builds and must keep the same completeness rule.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

UTC = timezone.utc
BASE_TIME = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


def minute_row(open_time: datetime, volume: str = "1") -> dict:
    return {
        "open_time": open_time,
        "open": Decimal("100"),
        "high": Decimal("110"),
        "low": Decimal("90"),
        "close": Decimal("105"),
        "volume": Decimal(volume),
    }


def insert_day(insert_candles, start: datetime = BASE_TIME) -> None:
    insert_candles(
        "BTCUSDT",
        [minute_row(start + timedelta(minutes=index)) for index in range(1440)],
    )


def test_reporting_candles_exposes_every_interval(insert_candles, db_connection):
    insert_day(insert_candles)

    rows = db_connection.execute(
        "SELECT interval, interval_minutes, count(*) AS n "
        "FROM reporting.candles "
        "GROUP BY interval, interval_minutes "
        "ORDER BY interval_minutes"
    ).fetchall()

    assert [(row["interval"], row["n"]) for row in rows] == [
        ("1m", 1440),
        ("5m", 288),
        ("15m", 96),
        ("30m", 48),
    ]


def test_reporting_15m_view_returns_complete_ohlcv(insert_candles, db_connection):
    insert_day(insert_candles)

    row = db_connection.execute(
        "SELECT * FROM reporting.candles_15m ORDER BY bucket_start LIMIT 1"
    ).fetchone()

    assert row["interval"] == "15m"
    assert row["bucket_start"] == BASE_TIME
    assert row["open"] == Decimal("100")
    assert row["high"] == Decimal("110")
    assert row["low"] == Decimal("90")
    assert row["close"] == Decimal("105")
    assert row["volume"] == Decimal("15")
    assert row["source_candles"] == 15


def test_reporting_views_drop_incomplete_buckets(insert_candles, db_connection):
    insert_candles(
        "BTCUSDT",
        [minute_row(BASE_TIME + timedelta(minutes=index)) for index in range(14)],
    )

    count = db_connection.execute(
        "SELECT count(*) AS n FROM reporting.candles_15m"
    ).fetchone()["n"]
    assert count == 0


def test_reporting_daily_and_summary_views(insert_candles, db_connection):
    insert_day(insert_candles)

    daily = db_connection.execute(
        "SELECT * FROM reporting.daily_candles"
    ).fetchall()
    assert len(daily) == 1
    assert daily[0]["day_start"] == BASE_TIME
    assert daily[0]["source_candles"] == 1440
    assert daily[0]["volume"] == Decimal("1440")

    summary = db_connection.execute(
        "SELECT * FROM reporting.symbol_summary"
    ).fetchone()
    assert summary["symbol"] == "BTCUSDT"
    assert summary["candle_count"] == 1440

    latest = db_connection.execute(
        "SELECT * FROM reporting.latest_prices"
    ).fetchone()
    assert latest["last_close"] == Decimal("105")
