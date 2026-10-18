#!/usr/bin/env python3
"""
Import the bundled historical 1-minute CSV files into PostgreSQL.

    python import_data.py            # from the backend/ directory
    docker compose exec backend python import_data.py

What it does
------------
1. reads every ``*.csv`` file in the data directory (``DATA_DIR``, default
   ``<repo>/data``); the file name is the symbol, e.g. ``BTCUSDT.csv``;
2. parses every row and validates the timestamp and the OHLCV values;
3. inserts the valid rows with
   ``INSERT ... ON CONFLICT (symbol, open_time) DO NOTHING``;
4. prints how many rows were imported, skipped or rejected, and verifies what
   is stored in the database afterwards.

Conflict policy (deterministic)
-------------------------------
``ON CONFLICT (symbol, open_time) DO NOTHING``: a candle that is already stored
is left exactly as it is and counted as "already in database". The importer
never overwrites a stored candle with the content of a CSV file, so running it
twice can never change or duplicate the data. To deliberately replace the data,
reset the database (see the README: ``docker compose down -v``).

Validation rules
----------------
A row is **rejected**, never repaired, when any of these checks fails:

* the header must be exactly ``open_time,open,high,low,close,volume``;
* ``open_time`` must be ISO-8601 with a timezone (``2026-10-11T00:00:00Z``)
  and aligned to a whole minute;
* ``open``, ``high``, ``low``, ``close`` must be positive numbers;
* ``volume`` must be a number ``>= 0``;
* ``high`` must not be lower than open, close or low;
* ``low`` must not be higher than open, close or high;
* the same ``open_time`` must not appear twice in one file.

Rejected rows are reported with file name, line number and reason, so nothing is
silently treated as valid data. Missing minutes are *not* filled in: they simply
stay missing, and the aggregation omits the buckets they belong to.
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from app import database

EXPECTED_HEADER = ["open_time", "open", "high", "low", "close", "volume"]
PRICE_FIELDS = ("open", "high", "low", "close")
BATCH_SIZE = 2000

INSERT_CANDLE_SQL = """\
INSERT INTO candles (symbol, open_time, open, high, low, close, volume)
VALUES (%(symbol)s, %(open_time)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s)
ON CONFLICT (symbol, open_time) DO NOTHING;"""

COUNT_CANDLES_SQL = "SELECT count(*) AS n FROM candles WHERE symbol = %(symbol)s;"


class RowRejected(Exception):
    """Raised for a row that breaks one of the documented validation rules."""


@dataclass
class ParsedFile:
    """Result of reading and validating one CSV file."""

    path: Path
    symbol: str
    rows: list[dict] = field(default_factory=list)
    rejected: list[tuple[int, str]] = field(default_factory=list)  # (line number, reason)
    duplicates_in_file: int = 0
    gaps: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing and validation
# ---------------------------------------------------------------------------


def parse_timestamp(raw: str) -> datetime:
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RowRejected(f"open_time is not an ISO-8601 timestamp: {raw!r}") from exc
    if parsed.tzinfo is None:
        raise RowRejected(
            f"open_time has no timezone: {raw!r} (expected UTC, e.g. 2026-10-11T00:00:00Z)"
        )
    parsed = parsed.astimezone(timezone.utc)
    if parsed.second != 0 or parsed.microsecond != 0:
        raise RowRejected(f"open_time is not aligned to a whole minute: {raw!r}")
    return parsed


def parse_decimal(raw: str, field_name: str) -> Decimal:
    text = raw.strip()
    if not text:
        raise RowRejected(f"{field_name} is empty")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise RowRejected(f"{field_name} is not a number: {raw!r}") from exc
    if not value.is_finite():
        raise RowRejected(f"{field_name} is not a finite number: {raw!r}")
    return value


def parse_row(fields: list[str]) -> tuple[datetime, dict[str, Decimal]]:
    """Validate one CSV row and return (open_time, {field: Decimal})."""
    if len(fields) != len(EXPECTED_HEADER):
        raise RowRejected(
            f"expected {len(EXPECTED_HEADER)} columns, found {len(fields)}"
        )

    open_time = parse_timestamp(fields[0])
    values = {
        name: parse_decimal(fields[index], name)
        for index, name in enumerate(EXPECTED_HEADER[1:], start=1)
    }

    for name in PRICE_FIELDS:
        if values[name] <= 0:
            raise RowRejected(f"{name} must be greater than 0, found {values[name]}")

    if values["volume"] < 0:
        raise RowRejected(f"volume must not be negative, found {values['volume']}")

    highest = max(values["open"], values["close"], values["low"])
    if values["high"] < highest:
        raise RowRejected(
            f"high ({values['high']}) is lower than open/close/low ({highest})"
        )
    lowest = min(values["open"], values["close"], values["high"])
    if values["low"] > lowest:
        raise RowRejected(
            f"low ({values['low']}) is higher than open/close/high ({lowest})"
        )

    return open_time, values


def read_csv_file(path: Path) -> ParsedFile:
    """Read one CSV file and split its rows into valid and rejected ones."""
    symbol = path.stem.upper()
    parsed = ParsedFile(path=path, symbol=symbol)
    seen_timestamps: set[datetime] = set()

    # utf-8-sig tolerates a byte-order mark at the start of the file.
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            parsed.rejected.append((0, "file is empty"))
            return parsed

        header = [name.strip().lower() for name in header]
        if header != EXPECTED_HEADER:
            raise SystemExit(
                f"[import] {path.name}: unexpected header {header}. "
                f"Expected exactly: {','.join(EXPECTED_HEADER)}"
            )

        for line_number, fields in enumerate(reader, start=2):
            if not fields or all(not value.strip() for value in fields):
                continue  # skip blank lines
            try:
                open_time, values = parse_row(fields)
            except RowRejected as exc:
                parsed.rejected.append((line_number, str(exc)))
                continue

            if open_time in seen_timestamps:
                parsed.duplicates_in_file += 1
                parsed.rejected.append(
                    (line_number, f"duplicate open_time {open_time.isoformat()} in file")
                )
                continue
            seen_timestamps.add(open_time)
            parsed.rows.append(
                {
                    "symbol": symbol,
                    "open_time": open_time,
                    "open": values["open"],
                    "high": values["high"],
                    "low": values["low"],
                    "close": values["close"],
                    "volume": values["volume"],
                }
            )

    parsed.rows.sort(key=lambda row: row["open_time"])
    parsed.gaps = find_gaps(parsed.rows)
    return parsed


def find_gaps(rows: list[dict]) -> list[str]:
    """
    List the missing minutes inside a file's own time range.

    Gaps are reported, never filled in: the aggregation drops the buckets that
    are not complete, so a hole in the source data stays visible as a hole in
    the chart.
    """
    gaps: list[str] = []
    for previous, current in zip(rows, rows[1:]):
        difference = current["open_time"] - previous["open_time"]
        if difference.total_seconds() != 60:
            missing = int(difference.total_seconds() // 60) - 1
            gaps.append(
                f"{missing} minute(s) missing after {format_timestamp(previous['open_time'])}"
            )
    return gaps


# ---------------------------------------------------------------------------
# Database work
# ---------------------------------------------------------------------------


def find_csv_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise SystemExit(f"[import] data directory not found: {directory}")
    files = sorted(path for path in directory.glob("*.csv") if path.is_file())
    if not files:
        raise SystemExit(f"[import] no CSV files found in {directory}")
    return files


def symbol_exists(conn: psycopg.Connection, symbol: str) -> bool:
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM symbols WHERE symbol = %(symbol)s;", {"symbol": symbol})
        return cursor.fetchone() is not None


def count_candles(conn: psycopg.Connection, symbol: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute(COUNT_CANDLES_SQL, {"symbol": symbol})
        return cursor.fetchone()["n"]


def insert_rows(conn: psycopg.Connection, rows: list[dict]) -> int:
    """Insert rows, skipping candles that are already stored. Returns inserted count."""
    if not rows:
        return 0

    symbol = rows[0]["symbol"]
    before = count_candles(conn, symbol)
    with conn.cursor() as cursor:
        for start in range(0, len(rows), BATCH_SIZE):
            cursor.executemany(INSERT_CANDLE_SQL, rows[start : start + BATCH_SIZE])
    return count_candles(conn, symbol) - before


def stored_range(conn: psycopg.Connection, symbol: str) -> tuple[datetime | None, datetime | None]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT min(open_time) AS first, max(open_time) AS last FROM candles WHERE symbol = %(symbol)s;",
            {"symbol": symbol},
        )
        row = cursor.fetchone()
    return row["first"], row["last"]


def format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "n/a"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def report_file(parsed: ParsedFile, inserted: int) -> None:
    accepted = len(parsed.rows)
    already_present = accepted - inserted
    print(f"[import] {parsed.path.name} -> symbol {parsed.symbol}")
    print(f"         rows read .......... {accepted + len(parsed.rejected)}")
    print(f"         accepted ........... {accepted}")
    print(f"         rejected ........... {len(parsed.rejected)}")
    print(f"         duplicates in file . {parsed.duplicates_in_file}")
    print(f"         inserted ........... {inserted}")
    print(f"         already in database  {already_present} (skipped, existing rows kept)")

    if parsed.gaps:
        print(f"         ! missing minutes .. {len(parsed.gaps)} gap(s) in the source file")
        for gap in parsed.gaps[:10]:
            print(f"           {gap}")
    else:
        print("         missing minutes ..... 0 (continuous 1-minute series)")

    if parsed.rejected:
        print(f"         ! first rejected rows:")
        for line_number, reason in parsed.rejected[:10]:
            print(f"           line {line_number}: {reason}")
        if len(parsed.rejected) > 10:
            print(f"           ... and {len(parsed.rejected) - 10} more")


def print_database_summary(conn: psycopg.Connection, symbols: list[str]) -> None:
    print("\n[import] database contents after import:")
    total = 0
    with conn.cursor() as cursor:
        for symbol in symbols:
            first, last = stored_range(conn, symbol)
            count = count_candles(conn, symbol)
            total += count
            print(
                f"         {symbol:<8} {count:>7} candles  "
                f"{format_timestamp(first)} .. {format_timestamp(last)}"
            )
    print(f"         {'total':<8} {total:>7} candles")


def ensure_schema_is_ready(conn: psycopg.Connection) -> None:
    """Fail with a readable message when the tables have not been created yet."""
    try:
        conn.execute("SELECT 1 FROM symbols LIMIT 1")
        conn.execute("SELECT 1 FROM candles LIMIT 1")
    except psycopg.errors.UndefinedTable as exc:
        raise SystemExit(
            "[import] the application tables do not exist yet. "
            "Run `python -m app.init_db` first."
        ) from exc


def main() -> int:
    data_directory = database.data_dir()
    files = find_csv_files(data_directory)
    print(f"[import] data directory: {data_directory}")
    print(f"[import] files: {', '.join(path.name for path in files)}")

    url = database.database_url()
    total_inserted = 0
    total_rejected = 0
    imported_symbols: list[str] = []

    with psycopg.connect(url, row_factory=dict_row) as conn:
        ensure_schema_is_ready(conn)

        for path in files:
            parsed = read_csv_file(path)
            if not symbol_exists(conn, parsed.symbol):
                raise SystemExit(
                    f"[import] {parsed.symbol} is missing from the symbols table. "
                    f"Run `python -m app.init_db` first."
                )

            print()
            inserted = insert_rows(conn, parsed.rows)
            # Commit per file so one bad file cannot roll back the others.
            conn.commit()
            report_file(parsed, inserted)
            first, last = stored_range(conn, parsed.symbol)
            print(f"         stored range  ....... {format_timestamp(first)} .. {format_timestamp(last)}")

            total_inserted += inserted
            total_rejected += len(parsed.rejected)
            imported_symbols.append(parsed.symbol)

        print_database_summary(conn, imported_symbols)

    print(
        f"\n[import] finished: {total_inserted} rows inserted, "
        f"{total_rejected} rows rejected."
    )
    if total_rejected:
        print("[import] WARNING: rejected rows were not imported. See the list above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
