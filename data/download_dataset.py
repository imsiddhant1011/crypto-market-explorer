#!/usr/bin/env python3
"""
Download real historical 1-minute candlesticks from Binance and write the CSV
files used by this project.

Source
------
Binance publishes free historical market data at https://data.binance.vision/
(Spot -> Monthly / Daily klines). This script uses the *daily* 1-minute archives:

    https://data.binance.vision/data/spot/daily/klines/{SYMBOL}/1m/{SYMBOL}-1m-{YYYY-MM-DD}.zip

Each archive contains one CSV with the columns:

    open_time, open, high, low, close, volume, close_time,
    quote_volume, count, taker_buy_volume, taker_buy_quote_volume, ignore

Notes about the raw format:
  * `open_time` is a Unix epoch timestamp in milliseconds (Binance switched some
    archives to microseconds; this script detects that and normalises to UTC).
  * No partner account, API key or authentication is required for these files.

Output
------
The script writes `data/{SYMBOL}.csv` with exactly six columns:

    open_time,open,high,low,close,volume

`open_time` is ISO-8601 UTC (e.g. 2026-10-11T00:00:00Z). Prices and volumes are
copied through as text, so the precision published by Binance is preserved - the
script never rounds values.

Usage
-----
    python3 data/download_dataset.py                      # latest 7 complete days
    python3 data/download_dataset.py --days 7 --end-date 2026-10-17

The application itself never downloads anything at runtime; the generated CSV
files are committed to the repository and imported into PostgreSQL by
`backend/import_data.py`.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_URL = "https://data.binance.vision/data/spot/daily/klines"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
OUTPUT_DIR = Path(__file__).resolve().parent
CSV_HEADER = ["open_time", "open", "high", "low", "close", "volume"]
# Binance CSV columns after open_time; only the first five are needed.
PRICE_VOLUME_COLUMNS = 6


def daily_archive_url(symbol: str, day: date) -> str:
    return f"{BASE_URL}/{symbol}/1m/{symbol}-1m-{day.isoformat()}.zip"


def download(url: str) -> bytes:
    """Fetch a URL and return its bytes, with a clear error on failure."""
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"[error] {url} -> HTTP {exc.code} (archive not published yet?)") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"[error] {url} -> {exc.reason} (no internet access?)") from exc


def parse_open_time(raw: str) -> datetime:
    """
    Binance writes open_time as milliseconds since the Unix epoch in most
    archives and as microseconds in newer ones. Normalise both to UTC.
    """
    value = int(raw.strip())
    unit = 1_000_000 if value > 10**14 else 1_000  # microseconds vs milliseconds
    return datetime.fromtimestamp(value / unit, tz=timezone.utc)


def rows_from_archive(payload: bytes, symbol: str, day: date) -> list[list[str]]:
    """Read the single CSV inside a Binance daily zip and normalise its rows."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise SystemExit(f"[error] {symbol} {day}: expected 1 CSV in the zip, found {names}")
        text = archive.read(names[0]).decode("utf-8")

    rows: list[list[str]] = []
    for line_number, raw_line in enumerate(csv.reader(io.StringIO(text)), start=1):
        if not raw_line or not raw_line[0].strip():
            continue
        if line_number == 1 and not raw_line[0].strip().isdigit():
            continue  # header row ("open_time", ...)
        if len(raw_line) < PRICE_VOLUME_COLUMNS:
            raise SystemExit(f"[error] {symbol} {day}: short row {raw_line!r}")
        open_time = parse_open_time(raw_line[0])
        rows.append([
            open_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            raw_line[1].strip(),
            raw_line[2].strip(),
            raw_line[3].strip(),
            raw_line[4].strip(),
            raw_line[5].strip(),
        ])
    return rows


def month_name_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def build_symbol(symbol: str, start_day: date, days: int) -> None:
    collected: dict[str, list[str]] = {}
    duplicates = 0

    for offset in range(days):
        day = start_day + timedelta(days=offset)
        url = daily_archive_url(symbol, day)
        print(f"  downloading {url}")
        rows = rows_from_archive(download(url), symbol, day)
        for row in rows:
            if row[0] in collected:
                duplicates += 1
            collected[row[0]] = row
        print(f"    {day}: {len(rows)} rows")

    ordered = [collected[key] for key in sorted(collected)]

    # Report gaps honestly instead of filling them in.
    gaps: list[tuple[str, str]] = []
    previous: datetime | None = None
    for row in ordered:
        current = datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if previous is not None and current - previous != timedelta(minutes=1):
            gaps.append((month_name_utc(previous), month_name_utc(current)))
        previous = current

    target = OUTPUT_DIR / f"{symbol}.csv"
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerows(ordered)

    first = ordered[0][0] if ordered else "n/a"
    last = ordered[-1][0] if ordered else "n/a"
    print(f"  wrote {target} ({len(ordered)} rows)")
    print(f"  range: {first} .. {last}")
    print(f"  duplicate timestamps dropped: {duplicates}")
    print(f"  gaps found: {len(gaps)}")
    for gap_start, gap_end in gaps[:10]:
        print(f"    missing between {gap_start} and {gap_end}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=7, help="number of consecutive daily archives (default: 7)")
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        help="last day to include, YYYY-MM-DD (default: yesterday, UTC)",
    )
    args = parser.parse_args()

    end_day = args.end_date or (datetime.now(timezone.utc).date() - timedelta(days=1))
    start_day = end_day - timedelta(days=args.days - 1)
    print(f"Fetching {args.days} days of 1m klines: {start_day} .. {end_day}\n")

    for symbol in SYMBOLS:
        print(f"{symbol}:")
        build_symbol(symbol, start_day, args.days)
        print()

    print("Done. These CSV files are the offline dataset bundled with the project.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
