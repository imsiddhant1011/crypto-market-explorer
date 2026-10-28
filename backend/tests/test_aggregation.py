"""
Aggregation tests: does PostgreSQL build the right OHLCV candles?

The data used here is tiny and fully deterministic, so every expected value can
be written out by hand.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app import aggregation, queries

UTC = timezone.utc
BASE_TIME = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)  # an epoch-aligned minute


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def epoch(moment: datetime) -> int:
    """Unix seconds, which is what the chart expects in `time`."""
    return int(moment.timestamp())


def fetch_candles(client, symbol: str = "BTCUSDT", interval: str = "15m", range_name: str = "1d") -> dict:
    response = client.get(
        "/api/candles", params={"symbol": symbol, "interval": interval, "range": range_name}
    )
    assert response.status_code == 200, response.text
    return response.json()


def minute_row(open_time: datetime, open_: str, close: str, volume: str = "1") -> dict:
    """
    One 1-minute candle built from an open and a close price.

    The high is 10 above the larger of the two and the low is 10 below the
    smaller one, so the expected max(high) / min(low) of a whole bucket can be
    calculated by hand.
    """
    high = max(Decimal(open_), Decimal(close)) + Decimal("10")
    low = min(Decimal(open_), Decimal(close)) - Decimal("10")
    return {
        "open_time": open_time,
        "open": Decimal(open_),
        "high": high,
        "low": low,
        "close": Decimal(close),
        "volume": Decimal(volume),
    }


# 15 minutes whose first open is *not* the smallest open and whose last close is
# *not* the largest close. That is what makes this data able to catch the classic
# mistake of writing min(open) / max(close) instead of "first" / "last".
OPENS_15 = [
    "1000", "900", "950", "980", "920", "960", "990", "940",
    "970", "910", "930", "995", "925", "945", "1005",
]
CLOSES_15 = [
    "1010", "1020", "1030", "1040", "1050", "1200", "1070", "1080",
    "1090", "1100", "1110", "1120", "1130", "1140", "1005",
]


def fifteen_minute_rows(start: datetime = BASE_TIME) -> list[dict]:
    rows = []
    for index, (open_, close) in enumerate(zip(OPENS_15, CLOSES_15)):
        rows.append(
            minute_row(start + timedelta(minutes=index), open_, close, volume=str(index + 1))
        )
    return rows


# ---------------------------------------------------------------------------
# OHLCV correctness
# ---------------------------------------------------------------------------


def test_candle_uses_first_open_and_last_close(insert_candles, client):
    """Open comes from the earliest minute, close from the latest one."""
    insert_candles("BTCUSDT", fifteen_minute_rows())

    data = fetch_candles(client, "BTCUSDT", "15m")

    assert data["candle_count"] == 1
    candle = data["candles"][0]
    assert candle["time"] == epoch(BASE_TIME)

    # first minute of the bucket (00:00) - not min(open), which would be 900
    assert candle["open"] == 1000.0
    # last minute of the bucket (00:14) - not max(close), which would be 1200
    assert candle["close"] == 1005.0


def test_high_low_and_volume_are_aggregated_over_the_bucket(insert_candles, client):
    insert_candles("BTCUSDT", fifteen_minute_rows())

    candle = fetch_candles(client, "BTCUSDT", "15m")["candles"][0]

    # max over all rows of max(open, close) + 10  ->  max(1200) + 10
    assert candle["high"] == 1210.0
    # min over all rows of min(open, close) - 10  ->  min(900) - 10
    assert candle["low"] == 890.0
    # 1 + 2 + ... + 15
    assert candle["volume"] == 120.0
    assert candle["open"] <= candle["high"]
    assert candle["low"] <= candle["close"]
    assert candle["low"] <= candle["high"]


@pytest.mark.parametrize(
    ("interval", "expected_candles"),
    [("5m", 288), ("15m", 96), ("30m", 48)],
)
def test_a_full_day_of_minutes_produces_the_expected_number_of_buckets(
    insert_candles, client, interval, expected_candles
):
    """24 hours of 1-minute data = 288 / 96 / 48 candles."""
    rows = [minute_row(BASE_TIME + timedelta(minutes=index), "100", "105") for index in range(1440)]
    insert_candles("BTCUSDT", rows)

    data = fetch_candles(client, "BTCUSDT", interval)

    assert data["candle_count"] == expected_candles
    assert data["candles"][0]["time"] == epoch(BASE_TIME)
    last_bucket = BASE_TIME + timedelta(minutes=1440 - int(interval[:-1]))
    assert data["candles"][-1]["time"] == epoch(last_bucket)
    # Candles are returned in chronological order.
    times = [candle["time"] for candle in data["candles"]]
    assert times == sorted(times)


# ---------------------------------------------------------------------------
# Completeness rules
# ---------------------------------------------------------------------------


def test_incomplete_bucket_is_omitted(insert_candles, client):
    """A bucket that is missing a source minute is never returned."""
    rows = [minute_row(BASE_TIME + timedelta(minutes=index), "100", "105") for index in range(30)]
    del rows[7]  # minute 00:07 never arrived

    insert_candles("BTCUSDT", rows)

    fifteen = fetch_candles(client, "BTCUSDT", "15m")
    assert fifteen["candle_count"] == 1
    assert fifteen["candles"][0]["time"] == epoch(BASE_TIME + timedelta(minutes=15))

    five = fetch_candles(client, "BTCUSDT", "5m")
    # The missing minute 00:07 only destroys the 00:05 bucket.
    assert [candle["time"] for candle in five["candles"]] == [
        epoch(BASE_TIME + timedelta(minutes=offset)) for offset in (0, 10, 15, 20, 25)
    ]


def test_gap_in_the_source_series_is_not_filled(insert_candles, client):
    """Missing minutes stay missing: no synthetic candle is invented."""
    rows = [
        minute_row(BASE_TIME + timedelta(minutes=index), "100", "105")
        for index in range(30)
        if not 15 <= index < 20
    ]
    insert_candles("BTCUSDT", rows)

    data = fetch_candles(client, "BTCUSDT", "15m")

    assert data["candle_count"] == 1
    assert [candle["time"] for candle in data["candles"]] == [epoch(BASE_TIME)]


def test_buckets_are_aligned_to_utc_clock_boundaries(insert_candles, client):
    """Buckets start at 10:00, 10:15, ... - not at the first row of the window."""
    start = BASE_TIME.replace(hour=10, minute=7)
    rows = [minute_row(start + timedelta(minutes=index), "100", "105") for index in range(15)]

    insert_candles("BTCUSDT", rows)
    # 10:07 .. 10:21 touches two clock-aligned buckets, neither of them complete.
    assert fetch_candles(client, "BTCUSDT", "15m")["candle_count"] == 0

    # Adding 10:00 .. 10:06 completes the 10:00 bucket.
    earlier = [minute_row(start - timedelta(minutes=index), "100", "105") for index in range(1, 8)]
    insert_candles("BTCUSDT", earlier)

    data = fetch_candles(client, "BTCUSDT", "15m")
    assert data["candle_count"] == 1
    assert data["candles"][0]["time"] == epoch(start.replace(minute=0))


def test_buckets_outside_the_selected_range_are_excluded(insert_candles, client):
    """Only the requested window is aggregated, even when more data is stored."""
    rows = [minute_row(BASE_TIME + timedelta(minutes=index), "100", "105") for index in range(1440 * 2)]
    insert_candles("BTCUSDT", rows)

    day = fetch_candles(client, "BTCUSDT", "15m", "1d")
    assert day["candle_count"] == 96
    assert day["window_start"] == "2026-01-02T00:00:00Z"
    assert day["window_end"] == "2026-01-03T00:00:00Z"

    week = fetch_candles(client, "BTCUSDT", "15m", "1w")
    assert week["candle_count"] == 96 * 2  # only two days of data exist
    assert week["window_start"] == "2025-12-27T00:00:00Z"

    month = fetch_candles(client, "BTCUSDT", "15m", "1m")
    assert month["candle_count"] == 96 * 2
    assert month["window_start"] == "2025-12-04T00:00:00Z"


# ---------------------------------------------------------------------------
# Window calculation (pure functions, no database needed)
# ---------------------------------------------------------------------------


def test_ceil_to_bucket_rounds_up_to_the_next_boundary():
    exact = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    assert aggregation.ceil_to_bucket(exact, 15) == exact
    assert aggregation.ceil_to_bucket(datetime(2026, 1, 1, 10, 0, 1, tzinfo=UTC), 15) == datetime(
        2026, 1, 1, 10, 15, tzinfo=UTC
    )
    assert aggregation.ceil_to_bucket(datetime(2026, 1, 1, 10, 14, 59, tzinfo=UTC), 15) == datetime(
        2026, 1, 1, 10, 15, tzinfo=UTC
    )


@pytest.mark.parametrize(
    ("interval", "expected_candles"),
    [("5m", 288), ("15m", 96), ("30m", 48)],
)
def test_window_contains_whole_buckets_only(interval, expected_candles):
    """The default window is one day wide and always ends on a bucket boundary."""
    last_minute = datetime(2026, 1, 7, 23, 59, tzinfo=UTC)

    start, end = aggregation.align_window(
        last_minute, queries.INTERVALS[interval], queries.RANGES["1d"]
    )

    assert start == datetime(2026, 1, 7, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 1, 8, 0, 0, tzinfo=UTC)
    assert (end - start) // timedelta(minutes=queries.INTERVALS[interval].minutes) == expected_candles


def test_one_week_window_is_anchored_on_the_last_minute():
    last_minute = datetime(2026, 1, 7, 23, 59, tzinfo=UTC)

    start, end = aggregation.align_window(
        last_minute, queries.INTERVALS["15m"], queries.RANGES["1w"]
    )

    assert end == datetime(2026, 1, 8, 0, 0, tzinfo=UTC)
    assert start == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


def test_one_month_window_is_anchored_on_the_last_minute():
    last_minute = datetime(2026, 1, 7, 23, 59, tzinfo=UTC)

    start, end = aggregation.align_window(
        last_minute, queries.INTERVALS["15m"], queries.RANGES["1m"]
    )

    assert end == datetime(2026, 1, 8, 0, 0, tzinfo=UTC)
    assert start == datetime(2025, 12, 9, 0, 0, tzinfo=UTC)
