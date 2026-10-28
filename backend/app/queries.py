"""
Every SQL statement this application runs, plus the educational text that is
sent to the browser for the "How this chart is calculated" panel.

Why everything lives in one module
----------------------------------
The SQL panel must never show a query that differs from the query that really
ran. The statement text, the interval definitions and the explanations are kept
together here, so the panel is rendered from exactly the same string that is
handed to PostgreSQL (`IntervalDefinition.sql`). Nothing else in the project
contains a copy of the aggregation query.

How the interval definitions are kept safe
------------------------------------------
The 5m / 15m / 30m variants of the query are built **once, at import time** from
the hard-coded definitions in `INTERVALS`. The `interval` value coming from the
browser is only ever used to *look up* one of these three prepared strings - an
unknown value is rejected before any SQL runs. No part of the query text is ever
built from user input.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

# ---------------------------------------------------------------------------
# Fixed SQL text
# ---------------------------------------------------------------------------

# All buckets are aligned to the Unix epoch, which is midnight UTC. Every
# interval used by this project (5, 15 and 30 minutes) divides a full day evenly,
# so bucket boundaries always fall on clean UTC clock times such as 00:00,
# 00:15, 00:30, ...
UTC_BUCKET_ORIGIN = "1970-01-01 00:00:00+00"

# The query that turns stored 1-minute candles into 5m / 15m / 30m candles.
#
# %(symbol)s, %(window_start)s and %(window_end)s are *parameters*: PostgreSQL
# receives the values separately from the SQL text, so they can never be read as
# SQL syntax (this is how SQL injection is prevented).
AGGREGATION_SQL_TEMPLATE = """\
SELECT
    date_bin(INTERVAL '{bin_literal}', open_time, TIMESTAMPTZ '{origin}') AS bucket_start,
    (array_agg(open  ORDER BY open_time ASC ))[1] AS open,
    max(high)                                     AS high,
    min(low)                                      AS low,
    (array_agg(close ORDER BY open_time DESC))[1] AS close,
    sum(volume)                                   AS volume,
    count(*)                                      AS source_candles
FROM candles
WHERE symbol = %(symbol)s
  AND open_time >= %(window_start)s
  AND open_time <  %(window_end)s
GROUP BY bucket_start
HAVING count(*) = {expected_candles}
ORDER BY bucket_start;"""

# The trading pairs shown in the dropdown.
SYMBOLS_SQL = """\
SELECT symbol, base_asset, quote_asset, display_name
FROM symbols
ORDER BY symbol;"""

# Oldest and newest stored 1-minute candle for one symbol. `max(open_time)` is
# what makes the default view "the latest 1 day of data we actually have"
# instead of "the last 24 hours according to the computer clock".
DATASET_RANGE_SQL = """\
SELECT min(open_time) AS first_open_time,
       max(open_time) AS last_open_time
FROM candles
WHERE symbol = %(symbol)s;"""

# Connection check used by GET /api/health.
HEALTH_SQL = """\
SELECT (SELECT count(*) FROM symbols) AS symbol_count,
       (SELECT count(*) FROM candles) AS candle_count,
       (SELECT max(open_time) FROM candles) AS latest_candle;"""


# ---------------------------------------------------------------------------
# Interval and range definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntervalDefinition:
    """One supported timeframe, its SQL, and the text that explains it."""

    name: str  # "15m" - the value used in the API
    minutes: int  # 15 - bucket size in minutes
    expected_candles: int  # one-minute source rows a complete bucket must contain
    sql: str  # the exact statement executed for this interval
    title: str
    explanation: str
    ohlcv_rules: list[str]
    completeness_rule: str
    concepts: list[dict]


@dataclass(frozen=True)
class RangeDefinition:
    """One supported historical range."""

    name: str  # "1d" - the value used in the API
    duration: timedelta
    label: str


RANGES: dict[str, RangeDefinition] = {
    "1d": RangeDefinition(
        name="1d",
        duration=timedelta(days=1),
        label="Latest 1 day of imported data",
    ),
    "1w": RangeDefinition(
        name="1w",
        duration=timedelta(weeks=1),
        label="Latest 1 week of imported data",
    ),
    "1m": RangeDefinition(
        name="1m",
        duration=timedelta(days=30),
        label="Latest 1 month (30 days) of imported data",
    ),
}

DEFAULT_RANGE = "1d"
DEFAULT_INTERVAL = "15m"


def _build_interval(minutes: int) -> IntervalDefinition:
    """Build the definition, the SQL and the teaching text for one timeframe."""
    name = f"{minutes}m"
    expected = minutes  # 1-minute source data => one row per minute of the bucket

    # The date_bin() stride and the HAVING count are the only two numbers that
    # change between intervals. Both come from this hard-coded integer.
    sql = AGGREGATION_SQL_TEMPLATE.format(
        bin_literal=f"{minutes} minutes",
        origin=UTC_BUCKET_ORIGIN,
        expected_candles=expected,
    )

    # Show the first few bucket start times for this interval, e.g. 00:00, 00:15, ...
    example_buckets = ", ".join(
        f"{minute // 60:02d}:{minute % 60:02d}" for minute in range(0, 60, minutes)
    )

    explanation = (
        f"PostgreSQL stores only 1-minute candles. To draw {name} candles it reads the "
        f"source rows of the selected symbol inside the selected time window, then splits "
        f"them into fixed {minutes}-minute buckets. "
        f"WHERE keeps the rows of one symbol inside the window "
        f"(WHERE symbol = %(symbol)s AND open_time >= %(window_start)s AND open_time < %(window_end)s). "
        f"date_bin(...) maps every 1-minute timestamp to the start of the "
        f"{minutes}-minute bucket it belongs to ({example_buckets}, ...), and "
        f"GROUP BY bucket_start collects the 1-minute rows of each bucket into one result row. "
        f"Inside every group, max(high) / min(low) give the extremes, sum(volume) adds the "
        f"volume up, and the chronologically first open and last close are picked with "
        f"array_agg(... ORDER BY open_time). "
        f"HAVING count(*) = {expected} then removes every bucket that is not complete, and "
        f"ORDER BY bucket_start returns the candles from oldest to newest."
    )

    ohlcv_rules = [
        "Open - the `open` of the earliest 1-minute candle in the bucket "
        "(`(array_agg(open ORDER BY open_time ASC))[1]`).",
        "High - the largest `high` of the bucket (`max(high)`).",
        "Low - the smallest `low` of the bucket (`min(low)`).",
        "Close - the `close` of the latest 1-minute candle in the bucket "
        "(`(array_agg(close ORDER BY open_time DESC))[1]`).",
        "Volume - the total traded volume of the bucket (`sum(volume)`).",
    ]

    completeness_rule = (
        f"A {name} bucket is returned only when it contains all {expected} expected "
        f"1-minute candles (`HAVING count(*) = {expected}`). Buckets with missing source "
        f"minutes are omitted - the gap stays visible in the chart instead of being filled "
        f"with invented prices."
    )

    concepts = [
        {
            "name": "WHERE - filtering rows before grouping",
            "detail": (
                "The WHERE clause keeps only the rows of one symbol inside the selected time "
                "window. It runs before GROUP BY, so PostgreSQL never has to aggregate the "
                "whole table. The three values are passed as parameters, not as SQL text."
            ),
        },
        {
            "name": "date_bin() + GROUP BY - time bucketing",
            "detail": (
                f"date_bin() assigns each 1-minute row to a fixed {minutes}-minute bucket that "
                "starts on a UTC clock time. GROUP BY then creates one result row per bucket. "
                "Buckets are calculated from timestamps only, so they are always aligned the "
                "same way - no matter which day is being viewed."
            ),
        },
        {
            "name": "max(high) and min(low) - aggregation functions",
            "detail": (
                "Aggregate functions collapse many rows into one value. The highest price "
                "reached during the bucket is the biggest high in it, and the lowest price is "
                "the smallest low. This works because HIGH and LOW are extremes."
            ),
        },
        {
            "name": "First open and last close - ordered aggregation",
            "detail": (
                "OPEN and CLOSE are not extremes, they are the values at the start and the end "
                "of the bucket. They are therefore taken with "
                "array_agg(value ORDER BY open_time), which sorts the bucket's rows by time "
                "and picks the first (for the open) or the last (for the close) one. "
                "min(open) or max(close) would return wrong prices."
            ),
        },
        {
            "name": "sum(volume) - additive measures",
            "detail": (
                f"Volume is additive: the volume traded in the {minutes} minutes of a bucket is the sum "
                "of the volume traded in each of those minutes."
            ),
        },
        {
            "name": "HAVING count(*) - completeness filter",
            "detail": (
                f"HAVING filters the groups created by GROUP BY (WHERE cannot do this). "
                f"Requiring exactly {expected} source rows per bucket guarantees that every "
                f"candle shown on the chart was built from complete data."
            ),
        },
        {
            "name": "ORDER BY - deterministic output",
            "detail": (
                "Charts need candles in chronological order, so the result is sorted by the "
                "bucket timestamp. SQL tables have no guaranteed order without ORDER BY."
            ),
        },
        {
            "name": "Primary key, foreign key and index",
            "detail": (
                "candles has the composite primary key (symbol, open_time): it makes duplicate "
                "minutes impossible and creates a B-tree index. The query above can use that "
                "index for its symbol + time-range filter, so only the needed rows are read. "
                "The foreign key candles.symbol -> symbols.symbol guarantees that a candle can "
                "only exist for a known trading pair."
            ),
        },
        {
            "name": "NUMERIC - exact decimal prices",
            "detail": (
                "Prices and volumes are stored as NUMERIC, not as floating point, so the values "
                "read back from the database are exactly the values that were imported."
            ),
        },
    ]

    return IntervalDefinition(
        name=name,
        minutes=minutes,
        expected_candles=expected,
        sql=sql,
        title=f"How {name} candles are calculated",
        explanation=explanation,
        ohlcv_rules=ohlcv_rules,
        completeness_rule=completeness_rule,
        concepts=concepts,
    )


INTERVALS: dict[str, IntervalDefinition] = {
    definition.name: definition for definition in (_build_interval(m) for m in (5, 15, 30))
}

# NOTE: this comprehension is the allowlist for the `interval` query parameter.
# `INTERVALS["5m"]`, `INTERVALS["15m"]`, `INTERVALS["30m"]` are the only valid values.
