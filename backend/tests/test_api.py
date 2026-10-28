"""
API tests: validation, response shape and error behaviour of the three endpoints.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app import database, queries

UTC = timezone.utc
BASE_TIME = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


def insert_day(insert_candles, symbol: str = "BTCUSDT", start: datetime = BASE_TIME) -> None:
    """Insert 24 hours of identical 1-minute candles."""
    rows = [
        {
            "open_time": start + timedelta(minutes=index),
            "open": Decimal("100"),
            "high": Decimal("110"),
            "low": Decimal("90"),
            "close": Decimal("105"),
            "volume": Decimal("1"),
        }
        for index in range(1440)
    ]
    insert_candles(symbol, rows)


# ---------------------------------------------------------------------------
# GET /api/symbols
# ---------------------------------------------------------------------------


def test_symbols_endpoint_returns_the_seeded_pairs(client):
    response = client.get("/api/symbols")

    assert response.status_code == 200
    symbols = {item["symbol"]: item for item in response.json()["symbols"]}
    assert set(symbols) == {
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "ADAUSDT",
        "DOGEUSDT",
    }
    assert symbols["BTCUSDT"] == {
        "symbol": "BTCUSDT",
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "display_name": "Bitcoin / Tether",
    }
    assert symbols["ETHUSDT"]["display_name"] == "Ether / Tether"
    assert symbols["SOLUSDT"]["display_name"] == "Solana / Tether"
    assert symbols["DOGEUSDT"]["base_asset"] == "DOGE"


def test_symbols_come_from_the_database_not_from_hardcoded_records(client, db_connection):
    """A symbol added to the table shows up in the API, so the list is real data."""
    db_connection.execute(
        "INSERT INTO symbols (symbol, base_asset, quote_asset, display_name) "
        "VALUES ('TESTUSDT', 'TST', 'USDT', 'Test / Tether')"
    )
    db_connection.commit()

    try:
        symbols = {item["symbol"] for item in client.get("/api/symbols").json()["symbols"]}
        assert "TESTUSDT" in symbols

        # The extra symbol has no candles, which is not an error.
        response = client.get("/api/candles", params={"symbol": "TESTUSDT", "interval": "15m"})
        assert response.status_code == 200
        assert response.json()["candles"] == []
    finally:
        db_connection.execute("DELETE FROM symbols WHERE symbol = 'TESTUSDT'")
        db_connection.commit()


# ---------------------------------------------------------------------------
# GET /api/candles - happy path
# ---------------------------------------------------------------------------


def test_candles_endpoint_returns_chart_ready_data(insert_candles, client):
    insert_day(insert_candles)

    response = client.get(
        "/api/candles", params={"symbol": "BTCUSDT", "interval": "15m", "range": "1d"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "BTCUSDT"
    assert data["display_name"] == "Bitcoin / Tether"
    assert data["interval"] == "15m"
    assert data["range"] == "1d"
    assert data["timezone"] == "UTC"
    assert data["candle_count"] == 96
    assert len(data["candles"]) == 96
    assert data["source_candles_per_bucket"] == 15

    first = data["candles"][0]
    assert set(first) == {"time", "open", "high", "low", "close", "volume"}
    assert isinstance(first["time"], int)  # Unix seconds, ready for the chart
    assert first["open"] == 100.0
    assert first["high"] == 110.0
    assert first["low"] == 90.0
    assert first["close"] == 105.0
    assert first["volume"] == 15.0

    times = [candle["time"] for candle in data["candles"]]
    assert times == sorted(times)
    assert (times[1] - times[0]) == 15 * 60  # one candle per 15 minutes


def test_default_interval_and_range_are_applied(insert_candles, client):
    insert_day(insert_candles)

    data = client.get("/api/candles", params={"symbol": "BTCUSDT"}).json()

    assert data["interval"] == "15m"
    assert data["range"] == "1d"
    assert data["candle_count"] == 96


@pytest.mark.parametrize(("interval", "expected"), [("5m", 288), ("15m", 96), ("30m", 48)])
def test_every_interval_can_be_requested(insert_candles, client, interval, expected):
    insert_day(insert_candles)

    data = client.get(
        "/api/candles", params={"symbol": "BTCUSDT", "interval": interval}
    ).json()

    assert data["candle_count"] == expected
    assert data["interval_seconds"] == int(interval[:-1]) * 60


def test_default_view_is_the_latest_24_hours_of_imported_data(insert_candles, client):
    """
    The window follows the newest stored candle, not the wall clock, so the
    application also works with historical files.
    """
    last_minute = datetime(2026, 1, 2, 23, 59, tzinfo=UTC)  # in the past
    insert_day(insert_candles, start=last_minute - timedelta(hours=23, minutes=59))

    data = client.get("/api/candles", params={"symbol": "BTCUSDT"}).json()

    assert data["dataset_last_timestamp"] == "2026-01-02T23:59:00Z"
    assert data["dataset_first_timestamp"] == "2026-01-02T00:00:00Z"
    assert data["window_start"] == "2026-01-02T00:00:00Z"
    assert data["window_end"] == "2026-01-03T00:00:00Z"
    assert data["candle_count"] == 96
    assert datetime.fromisoformat(data["window_end"].replace("Z", "+00:00")) < datetime.now(UTC)


def test_both_symbols_can_be_requested_separately(insert_candles, client):
    insert_day(insert_candles, symbol="BTCUSDT", start=BASE_TIME)
    insert_day(insert_candles, symbol="ETHUSDT", start=BASE_TIME + timedelta(days=1))

    bitcoin = client.get("/api/candles", params={"symbol": "BTCUSDT"}).json()
    ether = client.get("/api/candles", params={"symbol": "ETHUSDT"}).json()

    assert bitcoin["display_name"] == "Bitcoin / Tether"
    assert ether["display_name"] == "Ether / Tether"
    assert bitcoin["dataset_last_timestamp"] == "2026-01-01T23:59:00Z"
    assert ether["dataset_last_timestamp"] == "2026-01-02T23:59:00Z"


def test_empty_dataset_returns_an_empty_chart(insert_candles, client):
    data = client.get("/api/candles", params={"symbol": "ETHUSDT"}).json()

    assert data["candle_count"] == 0
    assert data["candles"] == []
    assert data["dataset_first_timestamp"] is None
    assert data["dataset_last_timestamp"] is None
    assert data["window_start"] is None


# ---------------------------------------------------------------------------
# GET /api/candles - validation
# ---------------------------------------------------------------------------


def test_unknown_symbol_is_rejected(client):
    response = client.get("/api/candles", params={"symbol": "NOPEUSDT"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "NOPEUSDT" in detail
    assert "BTCUSDT" in detail and "ETHUSDT" in detail


def test_missing_symbol_is_rejected(client):
    response = client.get("/api/candles", params={"interval": "15m"})

    assert response.status_code == 422


@pytest.mark.parametrize("interval", ["1m", "1h", "15", "15m; DROP TABLE candles", ""])
def test_invalid_interval_is_rejected(client, interval):
    response = client.get("/api/candles", params={"symbol": "BTCUSDT", "interval": interval})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "range_name", ["1h", "30d", "all", "7d", "24h; DROP TABLE candles"]
)
def test_invalid_range_is_rejected(client, range_name):
    response = client.get(
        "/api/candles", params={"symbol": "BTCUSDT", "range": range_name}
    )

    assert response.status_code == 422


def test_one_month_range_only_returns_stored_data(insert_candles, client):
    insert_day(insert_candles)

    data = client.get(
        "/api/candles", params={"symbol": "BTCUSDT", "range": "1m"}
    ).json()

    # Only one day is stored, so a one-month window still returns 96 candles.
    assert data["range"] == "1m"
    assert data["candle_count"] == 96


# ---------------------------------------------------------------------------
# Educational SQL panel
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("interval", "bin_literal", "expected_rows"),
    [("5m", "5 minutes", 5), ("15m", "15 minutes", 15), ("30m", "30 minutes", 30)],
)
def test_education_block_matches_the_requested_interval(
    insert_candles, client, interval, bin_literal, expected_rows
):
    insert_day(insert_candles)

    education = client.get(
        "/api/candles", params={"symbol": "BTCUSDT", "interval": interval}
    ).json()["education"]

    assert education["title"] == f"How {interval} candles are calculated"
    # The displayed SQL is the statement that was executed for this interval ...
    assert f"INTERVAL '{bin_literal}'" in education["sql"]
    assert f"HAVING count(*) = {expected_rows}" in education["sql"]
    assert "max(high)" in education["sql"]
    assert "min(low)" in education["sql"]
    assert "sum(volume)" in education["sql"]
    # ... including its parameters, which are sent separately from the SQL text.
    assert "%(symbol)s" in education["sql"]
    assert "BTCUSDT" not in education["sql"]
    assert education["parameters"]["symbol"] == "BTCUSDT"
    assert education["parameters"]["window_start"] == "2026-01-01T00:00:00Z"

    assert education["ohlcv_rules"] and education["concepts"]
    concept_names = " ".join(concept["name"] for concept in education["concepts"])
    for keyword in ("WHERE", "date_bin", "GROUP BY", "max(high)", "HAVING", "ORDER BY", "index"):
        assert keyword in concept_names


def test_education_templates_are_not_interchangeable():
    """Each interval really has its own two numbers (stride and bucket size)."""
    assert "INTERVAL '5 minutes'" in queries.INTERVALS["5m"].sql
    assert "HAVING count(*) = 5" in queries.INTERVALS["5m"].sql
    assert "INTERVAL '30 minutes'" in queries.INTERVALS["30m"].sql
    assert "HAVING count(*) = 30" in queries.INTERVALS["30m"].sql
    assert queries.INTERVALS["5m"].sql != queries.INTERVALS["30m"].sql


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------


def test_health_reports_a_working_database(insert_candles, client):
    insert_day(insert_candles)

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "reachable"
    assert body["symbols"] == 7
    assert body["candles"] == 1440
    assert body["latest_candle_utc"] == "2026-01-01T23:59:00Z"


def test_health_reports_an_unreachable_database(client, monkeypatch):
    """A broken database connection becomes HTTP 503, not a stack trace."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:59999/does_not_exist")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "1")
    database.close_pool()

    response = client.get("/api/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["database"] == "unreachable"
    assert "detail" in body
    assert "Traceback" not in response.text


def test_root_endpoint_points_to_the_documentation(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "/api/candles" in " ".join(response.json()["endpoints"])
