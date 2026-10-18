"""
Database constraint tests.

These tests check that the rules declared in `database/init.sql` really protect
the data: the primary key, the foreign key and the CHECK constraints.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg
import pytest

from import_data import INSERT_CANDLE_SQL  # the importer's real INSERT statement

UTC = timezone.utc
OPEN_TIME = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

# A valid candle; individual tests override single fields.
VALID_CANDLE = {
    "open_time": OPEN_TIME,
    "open": Decimal("100"),
    "high": Decimal("110"),
    "low": Decimal("90"),
    "close": Decimal("105"),
    "volume": Decimal("1"),
}

# The constraints are tested with a plain INSERT, so that the database itself
# has to reject the bad row (the importer's statement additionally ignores
# conflicts - see test_importer_conflict_policy_keeps_the_stored_candle).
PLAIN_INSERT_SQL = """\
INSERT INTO candles (symbol, open_time, open, high, low, close, volume)
VALUES (%(symbol)s, %(open_time)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s)"""


def insert_candle(conn: psycopg.Connection, symbol: str = "BTCUSDT", **overrides) -> None:
    conn.execute(PLAIN_INSERT_SQL, {"symbol": symbol, **VALID_CANDLE, **overrides})


def stored_candle(conn: psycopg.Connection, symbol: str = "BTCUSDT") -> dict | None:
    cursor = conn.execute(
        "SELECT * FROM candles WHERE symbol = %(symbol)s AND open_time = %(open_time)s",
        {"symbol": symbol, "open_time": OPEN_TIME},
    )
    return cursor.fetchone()


# ---------------------------------------------------------------------------
# Primary key and conflict policy
# ---------------------------------------------------------------------------


def test_duplicate_symbol_and_open_time_is_rejected(db_connection):
    """One minute of one symbol can only be stored once."""
    insert_candle(db_connection)
    db_connection.commit()

    # A different, otherwise valid candle for the same minute.
    with pytest.raises(psycopg.errors.UniqueViolation) as error:
        insert_candle(
            db_connection,
            open=Decimal("101"),
            high=Decimal("111"),
            low=Decimal("91"),
            close=Decimal("106"),
        )

    assert "candles_pkey" in str(error.value)
    db_connection.rollback()


def test_duplicate_symbol_row_is_rejected(db_connection):
    with pytest.raises(psycopg.errors.UniqueViolation):
        db_connection.execute(
            "INSERT INTO symbols (symbol, base_asset, quote_asset, display_name) "
            "VALUES ('BTCUSDT', 'BTC', 'USDT', 'Bitcoin / Tether')"
        )
    db_connection.rollback()


def test_importer_conflict_policy_keeps_the_stored_candle(db_connection):
    """
    The documented conflict policy is ON CONFLICT DO NOTHING: re-importing a
    minute that is already stored never overwrites it with different values.
    """
    insert_candle(db_connection, open=Decimal("100"))
    db_connection.commit()

    # The importer's own statement, fed with a *different* candle for that minute.
    db_connection.execute(
        INSERT_CANDLE_SQL,
        {
            "symbol": "BTCUSDT",
            **VALID_CANDLE,
            "open": Decimal("500"),
            "high": Decimal("510"),
            "low": Decimal("490"),
            "close": Decimal("505"),
            "volume": Decimal("999"),
        },
    )
    db_connection.commit()

    stored = stored_candle(db_connection)
    assert stored is not None
    assert stored["open"] == Decimal("100")
    assert stored["volume"] == Decimal("1")


# ---------------------------------------------------------------------------
# Foreign key
# ---------------------------------------------------------------------------


def test_candle_for_an_unknown_symbol_violates_the_foreign_key(db_connection):
    with pytest.raises(psycopg.errors.ForeignKeyViolation) as error:
        insert_candle(db_connection, symbol="FAKEUSDT")

    assert "candles_symbol_fkey" in str(error.value)
    db_connection.rollback()


def test_symbol_with_candles_cannot_be_deleted_by_accident(db_connection):
    """The foreign key also stops a symbol from disappearing while data exists."""
    insert_candle(db_connection)
    db_connection.commit()

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db_connection.execute("DELETE FROM symbols WHERE symbol = 'BTCUSDT'")
    db_connection.rollback()


# ---------------------------------------------------------------------------
# CHECK constraints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        # high is not the highest price of the candle
        ({"high": Decimal("95")}, "candles_high_is_highest"),   # below open and close
        ({"high": Decimal("89"), "low": Decimal("85")}, "candles_high_is_highest"),
        # low is not the lowest price of the candle
        ({"low": Decimal("102")}, "candles_low_is_lowest"),     # above open
        ({"low": Decimal("106")}, "candles_low_is_lowest"),     # above close
        # prices and volume
        ({"low": Decimal("0")}, "candles_low_positive"),
        ({"volume": Decimal("-1")}, "candles_volume_non_negative"),
        ({"volume": Decimal("-0.00000001")}, "candles_volume_non_negative"),
    ],
)
def test_single_invalid_rule_is_rejected_by_its_constraint(db_connection, overrides, constraint):
    """Each case breaks exactly one rule, so the reported constraint is unique."""
    with pytest.raises(psycopg.errors.CheckViolation) as error:
        insert_candle(db_connection, **overrides)

    assert constraint in str(error.value)
    db_connection.rollback()


@pytest.mark.parametrize(
    "overrides",
    [
        {"open": Decimal("0"), "low": Decimal("-1")},
        {"close": Decimal("0"), "low": Decimal("-1")},
        {"high": Decimal("0"), "low": Decimal("-1")},
        {"high": Decimal("-5"), "low": Decimal("-10")},
    ],
)
def test_non_positive_prices_are_rejected(db_connection, overrides):
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_candle(db_connection, **overrides)
    db_connection.rollback()


def test_valid_edge_cases_are_accepted(db_connection):
    """A flat minute (open = high = low = close) and zero volume are valid."""
    insert_candle(
        db_connection,
        open=Decimal("100"),
        high=Decimal("100"),
        low=Decimal("100"),
        close=Decimal("100"),
        volume=Decimal("0"),
    )
    insert_candle(db_connection, open_time=OPEN_TIME + timedelta(minutes=1))
    db_connection.commit()

    row = db_connection.execute(
        "SELECT count(*) AS n FROM candles WHERE symbol = 'BTCUSDT'"
    ).fetchone()
    assert row["n"] == 2


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


def test_composite_primary_key_is_the_only_index_on_candles(db_connection):
    """
    The composite primary key creates the index used by the time-range queries.
    The project deliberately adds no other index to this table.
    """
    rows = db_connection.execute(
        "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'candles'"
    ).fetchall()

    assert [row["indexname"] for row in rows] == ["candles_pkey"]
    index_definition = rows[0]["indexdef"]
    assert "UNIQUE" in index_definition
    assert "(symbol, open_time)" in index_definition
    assert "btree" in index_definition.lower()


def test_symbol_is_the_leftmost_index_column(db_connection):
    """`WHERE symbol = ... AND open_time >= ...` can use the composite index."""
    definition = db_connection.execute(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'candles_pkey'"
    ).fetchone()["indexdef"]

    assert definition.index("symbol") < definition.index("open_time")
