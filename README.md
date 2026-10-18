# Crypto Market Data Explorer

An educational **DBMS + data-visualisation** project: historical 1-minute
cryptocurrency candles are stored in PostgreSQL, aggregated into 5m / 15m / 30m
candles **with SQL**, and displayed as real candlestick and volume charts.

```
React + Vite + TradingView Lightweight Charts   →   FastAPI (Python)   →   PostgreSQL 16
                                  all three started with: docker compose up --build
```

The point of the project is to show how a relational database turns raw market
data into something you can look at:

* a small, normalised schema (`symbols`, `candles`) with a composite primary key,
  a foreign key and CHECK constraints;
* one SQL aggregation query that builds 5m / 15m / 30m candles from the stored
  1-minute rows (no pre-computed tables, no client-side aggregation);
* an index (created by the composite primary key) that serves the
  "one symbol, one time range" query, with a real `EXPLAIN` example;
* a chart dashboard that only ever displays what the database returned.

**This is not a trading platform and the data is not live.** It works completely
offline from a bundled CSV dataset.

---

## Table of contents

1. [Project introduction](#1-project-introduction)
2. [Architecture](#2-architecture)
3. [Technology choices and trade-offs](#3-technology-choices-and-trade-offs)
4. [The historical dataset](#4-the-historical-dataset)
5. [Database schema](#5-database-schema)
6. [The aggregation query, explained](#6-the-aggregation-query-explained)
7. [Indexes and query plans](#7-indexes-and-query-plans)
8. [Backend API](#8-backend-api)
9. [Frontend](#9-frontend)
10. [Setup, start, stop, reset](#10-setup-start-stop-reset)
11. [Tests](#11-tests)
12. [Project structure](#12-project-structure)
13. [Limitations](#13-limitations)
14. [Viva preparation: 18 questions and answers](#14-viva-preparation-18-questions-and-answers)

---

## 1. Project introduction

**Problem.** A month of 1-minute crypto data is over 40,000 rows per trading pair.
Nobody can read that. Traders and analysts therefore look at *aggregated* candles:
a 15-minute candle summarises 15 one-minute candles with five numbers
(open, high, low, close, volume).

**Goal.** Show that this summarising is a database job, not a JavaScript job.
The application therefore stores *only* 1-minute candles and asks PostgreSQL for
5m / 15m / 30m candles whenever the user changes the timeframe.

**What the application does**

* lets the user pick **BTCUSDT** or **ETHUSDT** (loaded from the `symbols` table);
* lets the user pick a timeframe: **5m, 15m, 30m** (default 15m);
* lets the user pick a historical range: **last 24 hours** (default) or last 7 days;
* draws real OHLC candlesticks and a volume histogram underneath them;
* shows the OHLCV values of any candle the user clicks;
* shows the **exact SQL query** that produced the visible chart, with an
  explanation of every DBMS concept involved.

**What the application deliberately does not do:** no logins, no portfolios, no
orders, no live price feed, no WebSocket, no external market-data calls at
runtime, no pre-computed candle tables, no arbitrary SQL execution.

---

## 2. Architecture

```
                        ┌──────────────────────────────────────────┐
                        │  Browser (http://localhost:5173)         │
                        │  React + Vite + Lightweight Charts       │
                        │  • pair dropdown   • 5m/15m/30m buttons  │
                        │  • candles + volume charts               │
                        │  • SQL education panel                   │
                        └───────────────┬──────────────────────────┘
                                        │ HTTP GET /api/...
                                        ▼
                        ┌──────────────────────────────────────────┐
                        │  FastAPI backend (http://localhost:8000) │
                        │  main.py        endpoints + validation   │
                        │  aggregation.py window calculation       │
                        │  queries.py     SQL + teaching metadata  │
                        └───────────────┬──────────────────────────┘
                                        │ parameterised SQL (psycopg 3)
                                        ▼
                        ┌──────────────────────────────────────────┐
                        │  PostgreSQL 16 (docker volume)           │
                        │  symbols(symbol PK, ...)                 │
                        │  candles(symbol, open_time) PK, 1-minute │
                        └──────────────────────────────────────────┘
                                        ▲
                                        │ one-time import (idempotent)
                        ┌───────────────┴──────────────────────────┐
                        │  data/BTCUSDT.csv, data/ETHUSDT.csv      │
                        │  7 days of real 1-minute candles         │
                        │  (downloaded once, then offline)         │
                        └──────────────────────────────────────────┘
```

### Startup order (what `docker compose up --build` does)

1. **db** starts PostgreSQL 16, creates the databases and the volume, and reports
   healthy through a `pg_isready` healthcheck.
2. **backend** waits for that healthcheck, then `backend/start.sh` runs
   `python -m app.init_db` → applies `database/init.sql` (tables + symbol seed,
   idempotent) → runs `python import_data.py` → imports the CSV files
   (idempotent: duplicates are skipped) → starts uvicorn on port 8000.
3. **frontend** serves the built React bundle (Vite preview) on port 5173.

### The CSV import process

```
data/BTCUSDT.csv ─┐
                  ├─► import_data.py ─► validate every row ─► INSERT ... ON CONFLICT DO NOTHING ─► candles table
data/ETHUSDT.csv ─┘        │                                        │
                           └─ report: accepted / rejected /           └─ rerunnable: existing rows are kept,
                              duplicates / gaps / stored range           nothing is duplicated or overwritten
```

Details in [section 4](#4-the-historical-dataset).

---

## 3. Technology choices and trade-offs

| Choice | Why | Trade-off accepted |
| --- | --- | --- |
| **Plain PostgreSQL** (not TimescaleDB) | The project is about *core* SQL: `WHERE`, `GROUP BY`, `HAVING`, `ORDER BY`, constraints and indexes. `date_bin()` ships with PostgreSQL 14+, so time bucketing needs no extension, and the schema stays readable enough to explain in a viva. | TimescaleDB continuous aggregates would be faster on huge datasets, but they would hide the SQL this project exists to demonstrate, and they would add an extension the teacher cannot inspect in plain `psql`. |
| **FastAPI** | Gives request validation (`Literal` allowlists, types) for free, produces interactive API docs at `/docs`, and is thin enough that the whole backend is ~4 small files. | A heavier framework (Django) would bring an ORM and admin UI; both are unnecessary here because the SQL is the subject of the project. |
| **React + Vite** | Component state is a natural fit for "selected pair / timeframe / range / selected candle", and Vite builds the bundle in well under a second. | A plain HTML page with `fetch` would work too; React was chosen because the assignment asks for it and it keeps the chart/candle/panel state tidy. |
| **TradingView Lightweight Charts** | Purpose-built for financial candles: it draws real OHLC candles, has a histogram series for volume, handles zoom/pan, and is small (~40 kB gzipped). | It is a charting library, not a trading UI: no indicators, no order book, no live feed (which this project does not want anyway). |
| **Historical CSV files instead of a WebSocket** | The DBMS topics (schema, keys, aggregation, indexes) only need *data*, not a live stream. Files can be diffed, re-imported deterministically and checked into the repository, so the project runs offline and produces identical results every time. | No live "wow" effect. A WebSocket client would add reconnection logic and non-reproducible state for no benefit to the SQL demonstration. |
| **psycopg 3** | Small, well-documented PostgreSQL driver with real parameter binding and native `NUMERIC` → `Decimal` handling. | An ORM (SQLAlchemy) would generate the SQL for us, which is exactly what we want to *see* and explain. |
| **SQL init script** (not a migration framework) | `database/init.sql` is one readable file; the same file is used by the container, the importer and the tests, so there is a single source of truth. | No versioned migrations. For a project with a fixed schema this is simpler, and resetting is one documented command. |

---

## 4. The historical dataset

### Where the data comes from

| Property | Value |
| --- | --- |
| Source | Binance public historical market data, `https://data.binance.vision/` → *Spot → Daily klines* (1-minute archives) |
| Exact URLs | `https://data.binance.vision/data/spot/daily/klines/{SYMBOL}/1m/{SYMBOL}-1m-{YYYY-MM-DD}.zip` |
| Prepared / downloaded on | **2026-10-18** (the day after the newest included day, so every day is complete) |
| Symbols | `BTCUSDT`, `ETHUSDT` |
| Covered range (both files) | **2026-10-11 00:00:00 UTC → 2026-10-17 23:59:00 UTC** — exactly 7 consecutive days |
| Records per symbol | **10,080** 1-minute candles (7 × 24 × 60) |
| Gaps / invalid rows | **none** — the series is continuous, and every row passed the importer's validation |
| Timestamp convention | Unix epoch milliseconds in the source archives, stored as `TIMESTAMPTZ` in UTC; `open_time` is the *start* of the minute |
| Files in this repository | `data/BTCUSDT.csv`, `data/ETHUSDT.csv` (columns: `open_time,open,high,low,close,volume`) |
| Re-download | `python3 data/download_dataset.py --days 7 --end-date 2026-10-17` (needs internet, only for regenerating the files) |

The `open_time` values are written as ISO-8601 UTC strings
(`2026-10-11T00:00:00Z`) so the CSV can be read in a spreadsheet without
timezone surprises. Prices and volumes are copied through as text, so the
precision published by Binance is preserved — nothing is rounded by this project.

### Usage and licensing

The archives are published openly by Binance for public download; Binance links
its *"Binance Data Collection – Terms of Use"* from the data site
(`https://data.binance.vision/terms-of-use.html`). They are used here for
non-commercial, educational purposes. This project is **not** affiliated with,
sponsored by or endorsed by Binance, and it redistributes only a small
seven-day slice of publicly published data. If you want to reuse the dataset for
something commercial, read Binance's current terms yourself. Candlestick charts
are drawn with TradingView's [Lightweight Charts](https://github.com/tradingview/lightweight-charts)
(Apache-2.0), which renders the small "Charting by TradingView" attribution link.

### How the CSV files were produced

`data/download_dataset.py` (kept in the repository for transparency and
reproducibility):

1. downloads the daily `.zip` archive of each day for each symbol;
2. reads the CSV inside, normalising Binance's millisecond/microsecond
   `open_time` to UTC;
3. drops duplicate timestamps, sorts the rows and reports any missing minutes
   **instead of filling them in**;
4. writes `data/{SYMBOL}.csv`.

### How the data is loaded into PostgreSQL

`backend/import_data.py` (run automatically by the container, and rerunnable by
hand):

* reads every `*.csv` in the data directory; the file name is the symbol;
* validates every row — ISO-8601 UTC timestamp aligned to a whole minute,
  positive OHLC prices, volume `>= 0`, `high` not below open/close/low, `low` not
  above open/close/high, no duplicate timestamp in one file;
* rejects (never repairs, never silently accepts) malformed rows and prints them
  with their line number and the reason;
* inserts with `INSERT ... ON CONFLICT (symbol, open_time) DO NOTHING`
  — the documented conflict policy: **an existing candle is never overwritten**;
* reports `inserted`, `already in database`, `rejected`, `duplicates in file`,
  `missing minutes` and the resulting stored range per file.

Example run (first import, real output):

```
[import] data directory: /data
[import] files: BTCUSDT.csv, ETHUSDT.csv

[import] BTCUSDT.csv -> symbol BTCUSDT
         rows read .......... 10080
         accepted ........... 10080
         rejected ........... 0
         duplicates in file . 0
         inserted ........... 10080
         already in database  0 (skipped, existing rows kept)
         missing minutes ..... 0 (continuous 1-minute series)
         stored range  ....... 2026-10-11T00:00:00Z .. 2026-10-17T23:59:00Z
...
[import] finished: 20160 rows inserted, 0 rows rejected.
```

Running it a second time inserts 0 rows and reports `already in database 10080`
for each pair. To replace stored data on purpose, reset the database
(see [section 10](#10-setup-start-stop-reset)).

---

## 5. Database schema

`database/init.sql` is the whole schema. It creates **two** application tables.

```
   ┌──────────────────────────────┐              ┌─────────────────────────────────────────┐
   │ symbols                      │              │ candles                                 │
   ├──────────────────────────────┤              ├─────────────────────────────────────────┤
   │ symbol       VARCHAR(20)  PK │◄─────────────│ symbol    VARCHAR(20)      NOT NULL  FK │
   │ base_asset   VARCHAR(10)  NN │  1      many │ open_time TIMESTAMPTZ      NOT NULL     │
   │ quote_asset  VARCHAR(10)  NN │              │ open      NUMERIC          NOT NULL     │
   │ display_name VARCHAR(100) NN │              │ high      NUMERIC          NOT NULL     │
   └──────────────────────────────┘              │ low       NUMERIC          NOT NULL     │
              ▲                                  │ close     NUMERIC          NOT NULL     │
              │                                  │ volume    NUMERIC          NOT NULL     │
        seeded rows:                             └─────────────────────────────────────────┘
        BTCUSDT  BTC / USDT  "Bitcoin / Tether"   PRIMARY KEY (symbol, open_time)
        ETHUSDT  ETH / USDT  "Ether / Tether"     FOREIGN KEY (symbol) → symbols(symbol)
                                                  CHECKs on prices, volume and OHLC order
```

### `symbols` — which trading pairs exist

| Column | Type | Notes |
| --- | --- | --- |
| `symbol` | `VARCHAR(20)` | **Primary key** — e.g. `BTCUSDT` |
| `base_asset` | `VARCHAR(10)` | `NOT NULL` — e.g. `BTC` (the asset being priced) |
| `quote_asset` | `VARCHAR(10)` | `NOT NULL` — e.g. `USDT` (the currency it is priced in) |
| `display_name` | `VARCHAR(100)` | `NOT NULL` — shown in the dropdown |

The two supported pairs are inserted by the same script with
`ON CONFLICT (symbol) DO NOTHING`, so seeding is idempotent. The frontend reads
this table through `GET /api/symbols`; nothing in React hard-codes the pairs.

### `candles` — one row per (symbol, minute)

| Column | Type | Notes |
| --- | --- | --- |
| `symbol` | `VARCHAR(20)` | `NOT NULL`, part of the primary key, FK to `symbols` |
| `open_time` | `TIMESTAMPTZ` | `NOT NULL`, part of the primary key, **start** of the minute, always UTC |
| `open` | `NUMERIC` | `NOT NULL`, price at the start of the minute |
| `high` | `NUMERIC` | `NOT NULL`, highest price in the minute |
| `low` | `NUMERIC` | `NOT NULL`, lowest price in the minute |
| `close` | `NUMERIC` | `NOT NULL`, price at the end of the minute |
| `volume` | `NUMERIC` | `NOT NULL`, traded volume during the minute |

Why `NUMERIC` and not `DOUBLE PRECISION`: binary floating point cannot represent
`0.1` exactly and accumulates rounding error. Prices and volumes are decimal
values, so they are stored as exact decimals and read back unchanged.

**Constraints declared on `candles`**

| Constraint | Kind | What it prevents |
| --- | --- | --- |
| `candles_pkey PRIMARY KEY (symbol, open_time)` | primary key | the same minute of the same symbol existing twice; also creates the index used by the queries |
| `candles_symbol_fkey FOREIGN KEY (symbol) REFERENCES symbols(symbol)` | foreign key | candles for a pair that does not exist (and deleting a symbol that still has candles) |
| `candles_open_positive`, `candles_high_positive`, `candles_low_positive`, `candles_close_positive` | CHECK | any non-positive price |
| `candles_volume_non_negative` | CHECK | negative volume |
| `candles_high_is_highest CHECK (high >= open AND high >= close AND high >= low)` | CHECK | a "high" that is not the highest of the candle |
| `candles_low_is_lowest CHECK (low <= open AND low <= close AND low <= high)` | CHECK | a "low" that is not the lowest of the candle |

The database therefore refuses inconsistent rows *before* they can reach a chart,
no matter who inserts them. `backend/tests/test_constraints.py` proves each of
these rules by trying to break it.

---

## 6. The aggregation query, explained

The backend stores **only 1-minute candles**. Everything else is computed on
demand. This is the query that runs for the 15m timeframe (5m and 30m differ only
in the two highlighted numbers):

```sql
SELECT
    date_bin(INTERVAL '15 minutes', open_time, TIMESTAMPTZ '1970-01-01 00:00:00+00') AS bucket_start,
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
HAVING count(*) = 15
ORDER BY bucket_start;
```

Step by step:

1. **`WHERE symbol = %(symbol)s AND open_time >= %(window_start)s AND open_time < %(window_end)s`**
   Runs *before* grouping. It keeps only the rows of one pair inside the selected
   window (one day or seven days). Fewer rows to aggregate, and it is the part of
   the query the primary-key index can serve.
2. **`date_bin(INTERVAL '15 minutes', open_time, TIMESTAMPTZ '1970-01-01 …')`**
   Time bucketing: every minute is mapped to the start of the 15-minute bucket it
   belongs to (`00:00`, `00:15`, `00:30`, …). The third argument is the origin;
   using the Unix epoch (midnight UTC) is what makes the buckets line up with
   clean UTC clock times. All three intervals (5, 15, 30 minutes) divide a day
   evenly, so bucket boundaries are always consistent.
3. **`GROUP BY bucket_start`**
   Collapses each bucket's 15 one-minute rows into exactly one result row — one
   row per candle.
4. **`max(high)` / `min(low)`**
   HIGH is the largest price reached during the bucket and LOW is the smallest, so
   they are *extreme values*: maxima and minima over the group.
5. **`(array_agg(open ORDER BY open_time ASC))[1]`** and
   **`(array_agg(close ORDER BY open_time DESC))[1]`**
   OPEN and CLOSE are *positional* values: the price at the first and at the last
   minute of the bucket. `array_agg(... ORDER BY open_time)` collects the group's
   values in chronological order, and `[1]` takes the first element — the earliest
   open, or (with `DESC`) the latest close. This is why ordering matters.
6. **`sum(volume)`**
   Volume is additive: the volume of 15 minutes is the sum of their volumes.
7. **`HAVING count(*) = 15`**
   `HAVING` filters *groups* (as opposed to `WHERE`, which filters rows). A bucket
   is only returned when all 15 expected minutes are present. Incomplete buckets
   are left out of the result — the gap stays a gap in the chart.
8. **`ORDER BY bucket_start`**
   Returns the candles oldest → newest, which is the order a chart needs.

### How one minute becomes three timeframes

Identical source rows, different bucket width and different completeness rule:

```
1-minute source rows (candles table)
00:00 … 00:14  00:15 … 00:29  00:30 … 00:44  00:45 …
   │              │              │              │
   ├── 5m  → 3 candles per 15 minutes, each built from 5 source rows   (HAVING count(*) = 5)
   ├── 15m → 1 candle  per 15 minutes, built from 15 source rows       (HAVING count(*) = 15)
   └── 30m → 1 candle  per 30 minutes, built from 30 source rows       (HAVING count(*) = 30)
```

So a full 24-hour window contains **288 five-minute**, **96 fifteen-minute** or
**48 thirty-minute** candles — exactly what the dashboard displays.

### Why `MAX(close)` would be wrong

`max(close)` returns the *highest* close in the bucket, but a candle's CLOSE is
the price at the **end** of the bucket — it can perfectly well be lower than the
closes of earlier minutes. Same for `min(open)`: OPEN is the price at the
**start** of the bucket, not the cheapest one. Only `high` and `low` are extremes
and may be aggregated with `max`/`min`. The test
`test_candle_uses_first_open_and_last_close` uses data where
`min(open) = 900 ≠ first open = 1000` and `max(close) = 1200 ≠ last close = 1005`,
so a query with the wrong functions fails immediately.

### Where the query lives

`backend/app/queries.py` holds the SQL text **and** the text that explains it, and
the API returns both in one response. The frontend displays
`education.sql`, which is literally the same string that was sent to PostgreSQL —
there is no second copy that could drift out of date. The placeholders
(`%(symbol)s`, `%(window_start)s`, `%(window_end)s`) are the parameters that were
bound to that statement, and the API returns their values too, so the panel can
show exactly which window was queried.

---

## 7. Indexes and query plans

### The index that exists, and why

```sql
CONSTRAINT candles_pkey PRIMARY KEY (symbol, open_time)
```

A primary key in PostgreSQL is implemented with a **unique B-tree index**. This
one is a *composite* index over two columns, and the column order matters:

* `symbol` is the **left-most** column, so a query that filters
  `WHERE symbol = 'BTCUSDT'` can use the index for the first part;
* `open_time` is the second column, so — for that same symbol — the index is also
  ordered by time. That turns `open_time >= x AND open_time < y` into a
  **range scan over a contiguous part of the index** instead of a scan of the
  whole table.

In other words, the index answers the whole `WHERE` clause of the aggregation
query. The project deliberately adds **no other index**: every extra index costs
storage and slows down every `INSERT`, and the primary key already covers the
only query pattern the application uses. (A hypothetical query like
`WHERE open_time > … ` without a symbol would *not* benefit, because the leading
column is missing — that is what "left-most prefix rule" means.)

### A representative `EXPLAIN` (real output from this dataset)

```sql
EXPLAIN (ANALYZE, BUFFERS, COSTS)
SELECT date_bin(INTERVAL '15 minutes', open_time, TIMESTAMPTZ '1970-01-01 00:00:00+00') AS bucket_start,
       (array_agg(open ORDER BY open_time ASC))[1] AS open,
       max(high) AS high, min(low) AS low,
       (array_agg(close ORDER BY open_time DESC))[1] AS close,
       sum(volume) AS volume, count(*) AS source_candles
FROM candles
WHERE symbol = 'BTCUSDT'
  AND open_time >= TIMESTAMPTZ '2026-10-17 00:00:00+00'
  AND open_time <  TIMESTAMPTZ '2026-10-18 00:00:00+00'
GROUP BY bucket_start
HAVING count(*) = 15
ORDER BY bucket_start;
```

```
 GroupAggregate  (cost=364.90..421.45 rows=7 width=176) (actual time=1.069..2.477 rows=96 loops=1)
   Group Key: (date_bin('00:15:00'::interval, open_time, '1970-01-01 00:00:00+00'::timestamp with time zone))
   Filter: (count(*) = 15)
   Buffers: shared hit=27
   ->  Sort  (cost=364.90..368.49 rows=1439 width=51) (actual time=0.970..1.058 rows=1440 loops=1)
         Sort Key: (date_bin(...)), open_time
         Sort Method: quicksort  Memory: 181kB
         ->  Bitmap Heap Scan on candles  (cost=42.63..289.41 rows=1439 width=51) (actual time=0.221..0.552 rows=1440 loops=1)
               Recheck Cond: (((symbol)::text = 'BTCUSDT'::text) AND (open_time >= '2026-10-17 00:00:00+00') AND (open_time < '2026-10-18 00:00:00+00'))
               Heap Blocks: exact=17
               ->  Bitmap Index Scan on candles_pkey  (cost=0.00..42.28 rows=1439 width=0) (actual time=0.190..0.190 rows=1440 loops=1)
                     Index Cond: (((symbol)::text = 'BTCUSDT'::text) AND (open_time >= '2026-10-17 00:00:00+00') AND (open_time < '2026-10-18 00:00:00+00'))
```

Reading it from the inside out:

* **`Bitmap Index Scan on candles_pkey`** — PostgreSQL used the primary-key index,
  with `symbol = 'BTCUSDT'` *and* the time window as the index condition. This is
  exactly the access path the composite key was designed for.
* **`Bitmap Heap Scan`** — the matching rows are fetched from the table
  (`Heap Blocks: exact=17`, i.e. only 17 table pages were touched).
* **`Sort` + `GroupAggregate`** — the rows are sorted by `(bucket_start, open_time)`
  and then grouped. `GroupAggregate` (instead of `HashAggregate`) is what makes
  the ordered `array_agg(... ORDER BY open_time)` cheap.
* **`Filter: (count(*) = 15)`** — the `HAVING`: 96 groups survived, so exactly 96
  complete 15-minute candles were returned.
* **`Buffers: shared hit=27`** — everything was already in the cache; no disk
  reads were needed for this query.

A narrow window uses the index even more directly (this is the same query shape
with a five-minute window):

```
 HashAggregate  (cost=4.44..4.50 rows=1 width=16) (actual time=0.062..0.062 rows=0 loops=1)
   Group Key: date_bin('00:15:00'::interval, open_time, '1970-01-01 00:00:00+00'::timestamp with time zone)
   Filter: (count(*) = 15)
   Rows Removed by Filter: 1
   ->  Index Only Scan using candles_pkey on candles  (cost=0.29..4.41 rows=5 width=8) (actual time=0.056..0.057 rows=5 loops=1)
         Index Cond: ((symbol = 'BTCUSDT'::text) AND (open_time >= '2026-10-17 12:00:00+00') AND (open_time < '2026-10-17 12:05:00+00'))
         Heap Fetches: 0
```

`Index Only Scan … Heap Fetches: 0` means the answer came **from the index alone**
— the table was never touched. The result is `rows=0` because five minutes can
never fill a fifteen-minute bucket; the `HAVING` threw the incomplete group away,
which is the completeness rule working.

### How to interpret a plan (the short version)

* Read it **inside out / bottom up**: each line feeds the line above it.
* `cost=start..total` is the planner's *estimate* (in arbitrary units, not
  milliseconds); `actual time=…` appears only with `ANALYZE` and is real.
* `rows=` is the estimated number of rows at that step; comparing it with
  `actual rows=` shows whether the planner's statistics were good.
* A **Seq Scan** reads the whole table; an **Index Scan** / **Index Only Scan** /
  **Bitmap Index Scan** uses an index.
* `Buffers: shared hit=…` counts pages found in the cache, `read=…` pages fetched
  from disk.

### Honest caveats

* **An index is not automatically faster.** On a *small* table PostgreSQL often
  chooses a sequential scan on purpose, because reading a few small pages
  sequentially can beat the overhead of walking an index. With the 20,160 rows of
  this dataset the planner used the index, but on a tiny test table (the pytest
  fixtures use a handful of rows) it may well decide that a `Seq Scan` is cheaper
  — that is a *correct* decision, not a missing index.
* Plans depend on **statistics** (`ANALYZE`), on how much of the table the filter
  is expected to return, on caching, on the `work_mem` setting, and on the
  PostgreSQL version. Run `EXPLAIN` yourself; do not memorise this output.
* An index speeds up reads but slows down writes and costs storage
  (`candles_pkey` is about 640 kB next to a 1.7 MB table here), which is why
  unused indexes are avoided.
* The plan above is the reason the query is *written* the way it is (symbol and
  time range in `WHERE`, both covered by the same composite key). This project
  deliberately does **not** ship a query-plan UI or benchmark harness.

---

## 8. Backend API

Base URL `http://localhost:8000`. Interactive docs: `/docs`. All responses are
JSON; all timestamps are UTC in ISO-8601 (`2026-10-17T23:59:00Z`).

### `GET /api/symbols`

```json
{
  "symbols": [
    {"symbol": "BTCUSDT", "base_asset": "BTC", "quote_asset": "USDT", "display_name": "Bitcoin / Tether"},
    {"symbol": "ETHUSDT", "base_asset": "ETH", "quote_asset": "USDT", "display_name": "Ether / Tether"}
  ]
}
```

Read from the `symbols` table — the dropdown is not hard-coded in React.

### `GET /api/candles?symbol=BTCUSDT&interval=15m&range=24h`

| Parameter | Allowed values | Default | Validation |
| --- | --- | --- | --- |
| `symbol` | any symbol that exists in the `symbols` table | required | unknown value → **400** with the list of supported symbols |
| `interval` | `5m`, `15m`, `30m` | `15m` | explicit allowlist (`Literal`) → other values → **422** |
| `range` | `24h`, `7d` | `24h` | explicit allowlist → other values → **422** |

Response (abridged):

```json
{
  "symbol": "BTCUSDT",
  "display_name": "Bitcoin / Tether",
  "interval": "15m",
  "interval_minutes": 15,
  "interval_seconds": 900,
  "range": "24h",
  "range_label": "Latest 24 hours of imported data",
  "timezone": "UTC",
  "window_start": "2026-10-17T00:00:00Z",
  "window_end": "2026-10-18T00:00:00Z",
  "dataset_first_timestamp": "2026-10-11T00:00:00Z",
  "dataset_last_timestamp": "2026-10-17T23:59:00Z",
  "source_candles_per_bucket": 15,
  "candle_count": 96,
  "candles": [
    {"time": 1792195200, "open": 81615.91, "high": 81633.36, "low": 81572.66, "close": 81633.35, "volume": 251.83045}
  ],
  "education": {
    "title": "How 15m candles are calculated",
    "sql": "SELECT ... FROM candles WHERE symbol = %(symbol)s AND ... HAVING count(*) = 15 ...",
    "parameters": {"symbol": "BTCUSDT", "window_start": "2026-10-17T00:00:00Z", "window_end": "2026-10-18T00:00:00Z"},
    "explanation": "PostgreSQL stores only 1-minute candles. ...",
    "ohlcv_rules": ["Open - the open of the earliest 1-minute candle ...", "..."],
    "completeness_rule": "A 15m bucket is returned only when it contains all 15 ...",
    "concepts": [{"name": "WHERE - filtering rows before grouping", "detail": "..."}]
  }
}
```

* `candles[].time` is **Unix time in seconds** (what Lightweight Charts expects),
  always the start of the bucket, UTC.
* `candles[].open/high/low/close/volume` are JSON numbers. `NUMERIC` values are
  read from PostgreSQL as exact `Decimal` objects and converted to JavaScript
  doubles only for JSON/chart use (a double carries ~16 significant digits, far
  more than a price needs; no rounding is applied and the database keeps the
  exact decimal). This conversion is the only place where precision is traded
  away, and it is deliberate — the chart library can only plot floating point.
* `window_start`/`window_end` describe the *queried* window: it ends at the first
  bucket boundary at or after `max(open_time) + 1 minute`, and starts a fixed
  range before it (**exclusive** end, **inclusive** start). Because both range
  lengths are whole numbers of buckets, every bucket inside the window is
  complete or absent — never half-queried.
* `dataset_first_timestamp` / `dataset_last_timestamp` are the oldest and newest
  stored 1-minute candles, i.e. what the database actually contains.
* An empty result is a normal response: `"candle_count": 0, "candles": []`. The
  API never invents candles to fill a chart.

### `GET /api/health`

```json
{"status": "ok", "database": "reachable", "symbols": 2, "candles": 20160, "latest_candle_utc": "2026-10-17T23:59:00Z"}
```

Returns **503** with `{"status": "error", "database": "unreachable", "detail": "…"}`
when PostgreSQL cannot be reached.

### Error handling and SQL safety

* Unknown symbols → `400`; unknown intervals/ranges → `422`; database problems →
  `503`; unexpected database errors → `500`. Bodies are short JSON messages, and
  internal stack traces stay in the server log.
* Every value is passed as a **bound parameter** (`%(symbol)s`), never spliced
  into SQL text. The only variable piece of SQL is the interval stride and the
  bucket size, and those come from three hard-coded definitions
  (`INTERVALS` in `queries.py`) selected by an allowlist lookup — user input can
  never become SQL syntax.
* The frontend has no endpoint to submit SQL. The SQL panel is display-only.

---

## 9. Frontend

**Left column** — trading-pair dropdown (from `/api/symbols`), timeframe buttons
(5m / 15m / 30m), historical-range buttons (last 24 hours / last 7 days),
the candlestick chart, the volume histogram below it, a footer with the chart
window and the last stored 1-minute timestamp, and the **selected candle** panel.

**Right column** — the educational panel: the SQL statement that was executed,
the parameter values bound to it, what the query does, the OHLCV rules, the
completeness rule, and the DBMS concepts demonstrated. It updates with the
timeframe, because the API returns the SQL *and* the text for the current
interval.

Behaviour worth knowing:

* **No client-side aggregation.** React only draws the array the API returned.
* **The default view is the latest 24 hours of data that exists in the database**
  — anchored on `max(open_time)`, not on the computer clock, so a historical
  dataset is displayed correctly offline.
* **Green candle when `close >= open`, red when `close < open`** (Lightweight
  Charts uses exactly that rule internally).
* **The two charts stay in sync**: the price chart and the volume chart subscribe
  to each other's visible logical range, so zooming, scrolling or refitting one
  moves the other. Both reserve the same 78 px for their price scale, so the plot
  areas line up exactly.
* **Disposal**: when a chart component unmounts it unsubscribes its click handler
  and calls `chart.remove()`, which disposes the chart, its series and its
  `ResizeObserver` (`autoSize: true`). The parent also unsubscribes its
  cross-chart sync handlers.
* **States**: a loading overlay while fetching, a readable error box with a
  *Try again* button when the API or database is unreachable, and an empty state
  that explains the completeness rule instead of drawing a fake line. While
  loading, the chart is emptied and the selected candle is cleared, so no stale
  data is ever visible.
* **Responsive**: below 1100 px the education panel moves underneath the chart
  column; chart heights and the layout adapt further below 700 px.
* Nothing on the page suggests live data: the header says the dataset is
  historical, no ticking prices, no "live" badge, and the footer states the exact
  covered range.

---

## 10. Setup, start, stop, reset

### Prerequisites

[Docker Desktop](https://www.docker.com/products/docker-desktop/) (Docker Engine
+ Compose v2). Nothing else — Python, Node and PostgreSQL all run inside
containers. (Docker must be running.)

### Start everything (one command)

```bash
cd crypto-market-explorer
docker compose up --build
```

Then open:

| What | URL |
| --- | --- |
| Dashboard | <http://localhost:5173> |
| API | <http://localhost:8000> |
| API documentation (Swagger UI) | <http://localhost:8000/docs> |
| API health check | <http://localhost:8000/api/health> |

The first run builds images and downloads base images/dependencies, so it needs
internet access. **After that the application runs completely offline**: the
market data is already in `data/*.csv`, it is imported into PostgreSQL, and no
runtime code contacts any external service. Use `docker compose up -d` once the
images are built if you prefer the services in the background.

### Environment configuration (optional)

Every value has a working development default, so configuration is optional.
To change something:

```bash
cp .env.example .env      # then edit .env
```

`.env.example` documents all variables: database name/user/password, the port
mappings, `DB_POOL_TIMEOUT` and the CORS origins. The passwords in it are
**local development values, not secrets** — do not reuse them anywhere else.
Source code never contains a credential: `DATABASE_URL` is read from the
environment at runtime, with a documented localhost fallback for running the
backend or the tests outside Docker.

### Running it on another computer (for example after cloning from GitHub)

Everything the application needs is in the repository — the historical CSVs
(~1.8 MB), the schema, the frontend build configuration. The only requirements
on the other machine are Docker Desktop (installed **and running**) and internet
access for the *first* `docker compose up --build`, which downloads the base
images and the Python/Node dependencies (a few minutes; the resulting images are
roughly 180–290 MB each). After that it runs offline.

Things that can go wrong on a fresh machine, and the fix:

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Cannot connect to the Docker daemon` | Docker Desktop is not running | start Docker Desktop and run the command again |
| `Bind for 0.0.0.0:5432 failed: port is already allocated` | a local PostgreSQL (or another service) already uses the port | `cp .env.example .env`, change `POSTGRES_PORT` (and/or `BACKEND_PORT`/`FRONTEND_PORT`), then `docker compose up --build` again |
| The dashboard shows "Cannot reach the API" on the very first start | the backend is still importing the 20,160 CSV rows | wait ~15 seconds and press **Try again**; check `docker compose logs backend` |
| Windows: the backend container exits with `./start.sh: not found` or `bad interpreter` | the shell scripts were checked out with Windows line endings | already prevented by the `.gitattributes` file in this repository — make sure it is committed, and re-clone if you copied the files by hand instead of cloning |

One limitation worth knowing: the frontend is a static bundle that is **compiled
with the API URL** (`http://localhost:8000`). That is correct whenever the
browser runs on the same machine as Docker. To demo it from another device,
rebuild the frontend with an address that device can reach:

```bash
docker compose build --build-arg VITE_API_BASE_URL=http://192.168.1.50:8000 frontend
docker compose up -d frontend
```

### Stop

```bash
docker compose down          # stop and remove the containers, keep the data
```

### Reset the database (and re-import from the CSVs)

```bash
docker compose down -v       # also deletes the PostgreSQL volume
docker compose up --build    # schema + symbols + import run again from scratch
```

That is the supported way to replace stored data: the importer itself never
overwrites existing candles.

### Common tasks

```bash
# re-run the importer by hand (safe: duplicates are skipped)
docker compose exec backend python import_data.py

# run the test suite inside the backend container
docker compose exec backend pytest -v

# open a psql prompt
docker compose exec db psql -U crypto -d crypto_market_explorer

# follow the API logs (schema init + import output is printed there)
docker compose logs -f backend

# frontend development with hot reload instead of the built bundle
cd frontend && npm install && npm run dev     # http://localhost:5173
```

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| The dashboard shows "Cannot reach the API" | `docker compose ps` — is `backend` up? `docker compose logs backend`. |
| Port 5432/8000/5173 already in use | change `POSTGRES_PORT` / `BACKEND_PORT` / `FRONTEND_PORT` in `.env` (and rebuild the frontend so the bundle points at the new backend port: `docker compose up -d --build frontend`). |
| Chart is empty although data exists | check `GET /api/health` (row count) and read the empty-state text: the window may contain no *complete* bucket. |
| Tests say the test database is missing | `docker compose down -v && docker compose up --build` recreates `crypto_test`; or `docker compose exec db createdb -U crypto crypto_test`. |

---

## 11. Tests

62 tests, all passing, all offline. They run against a **separate database**
(`crypto_test`, created when the PostgreSQL volume is initialised) so they never
touch the imported market data.

```bash
docker compose exec backend pytest -v
```

```
tests/test_aggregation.py  ..............   14 passed
tests/test_api.py          .............................   29 passed
tests/test_constraints.py  ...................   19 passed
```

`backend/tests/test_aggregation.py` — the OHLCV maths on small, hand-checked
datasets:

* the open comes from the earliest minute and the close from the latest minute
  (data is built so that `min(open)` and `max(close)` would give different,
  wrong answers);
* high is the maximum, low is the minimum, volume is the sum;
* one day of minutes produces 288 / 96 / 48 buckets for 5m / 15m / 30m;
* a bucket that is missing a source minute is omitted (and only that bucket);
* a gap in the source series is not filled;
* buckets align to UTC clock boundaries, not to the first row of the window;
* only buckets inside the selected range are returned;
* the window calculation (`ceil_to_bucket`, `align_window`) is unit-tested
  without a database.

`backend/tests/test_api.py` — the HTTP contract:

* `/api/symbols` returns the seeded pairs, and a row added to the table really
  appears in the response (proving the list is read from the database);
* `/api/candles` returns chart-ready data (integer Unix seconds, numeric OHLCV,
  chronological order, one candle per interval, correct counts per timeframe);
* the default view follows the newest stored candle and not the wall clock;
* invalid symbols (`400`) and invalid intervals/ranges (`422`) are rejected;
* an empty dataset returns `200` with `[]` rather than an error;
* the education block matches the requested interval, contains the parameter
  placeholders (never the literal symbol), and each interval has its own SQL;
* `/api/health` reports `ok`, and reports `503` when the database is unreachable.

`backend/tests/test_constraints.py` — the database defends itself:

* duplicate `(symbol, open_time)` is rejected by the primary key;
* the importer's `ON CONFLICT DO NOTHING` policy keeps the stored candle;
* a candle for an unknown symbol violates the foreign key;
* `high < open/close/low`, `low > open/close/high`, non-positive prices and
  negative volume are each rejected by the named CHECK constraint;
* the composite primary key is the only index on `candles`, it is UNIQUE and its
  first column is `symbol`.

The tests need no internet connection: the pytest fixtures build their own
candles in SQL.

---

## 12. Project structure

```
crypto-market-explorer/
├── docker-compose.yml            # db + backend + frontend in one command
├── .env.example                  # documented, optional configuration
├── .gitignore
├── .gitattributes                # keeps shell scripts LF-only on every OS
├── README.md
├── data/
│   ├── BTCUSDT.csv               # 10,080 real 1-minute candles (2026-10-11 .. 2026-10-17)
│   ├── ETHUSDT.csv               # 10,080 real 1-minute candles
│   └── download_dataset.py       # how the CSVs were produced (needs internet)
├── database/
│   ├── init.sql                  # schema, constraints, symbol seed (single source of truth)
│   └── initdb/
│       └── 01-create-test-database.sh   # creates crypto_test for pytest (runs once)
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── start.sh                  # wait for db -> init schema -> import -> uvicorn
│   ├── import_data.py            # CSV -> PostgreSQL importer (idempotent)
│   ├── app/
│   │   ├── main.py               # FastAPI endpoints, validation, error handling
│   │   ├── database.py           # connection pool, file locations
│   │   ├── queries.py            # the SQL + the teaching text shown in the UI
│   │   ├── aggregation.py        # window calculation, SQL execution, JSON shaping
│   │   └── init_db.py            # readiness wait + schema application
│   └── tests/
│       ├── conftest.py           # test database fixtures
│       ├── test_aggregation.py
│       ├── test_api.py
│       └── test_constraints.py
└── frontend/
    ├── Dockerfile
    ├── package.json / package-lock.json
    ├── vite.config.js
    ├── index.html
    └── src/
        ├── main.jsx
        ├── App.jsx               # state, data loading, chart synchronisation
        ├── api.js                # fetch wrapper + readable errors
        ├── format.js             # UTC/number formatting helpers
        ├── styles.css
        └── components/
            ├── MarketSelector.jsx      # pair dropdown, timeframe, range
            ├── CandlestickChart.jsx    # price pane + candle click selection
            ├── VolumeChart.jsx         # volume histogram, shares the time axis
            ├── CandleDetails.jsx       # the clicked candle
            └── SqlEducationPanel.jsx   # SQL + explanation + concepts
```

---

## 13. Limitations

* **Historical, not live.** The bundled dataset covers 2026-10-11 → 2026-10-17.
  Nothing in the application polls or streams: no WebSocket, no live prices, no
  order book, no trading.
* **Two symbols, three timeframes, two ranges.** The design generalises (add a
  row to `symbols`, add an entry to `INTERVALS` in `queries.py`), but only
  BTCUSDT/ETHUSDT and 5m/15m/30m are seeded and validated on purpose.
* **Seven days of data.** Longer windows would need more CSV files or a wider
  download; the query itself does not change.
* **First build needs internet** to pull Docker base images and pip/npm
  dependencies. Runtime does not, and neither do the tests.
* **Not production infrastructure.** Single PostgreSQL instance, a small
  connection pool, no cache, no queue, no authentication, no HTTPS. The ports are
  meant for a local demo machine, and the documented passwords are local
  development values.
* **No sub-minute data.** The stored granularity is one minute, so 1-minute
  candles (and anything below) cannot be served.

---

## 14. Viva preparation: 18 questions and answers

**1. What is a DBMS, and why use one here instead of a CSV file?**
A DBMS (Database Management System) stores data, enforces rules about it and
answers queries efficiently. A CSV file cannot stop a duplicate or an impossible
candle from being written, cannot enforce that every candle belongs to a known
symbol, and cannot answer "give me the 15-minute candles of BTCUSDT for
yesterday" without reading every line. PostgreSQL does all of that: constraints
protect the data, and `GROUP BY` answers the aggregation question server-side.

**2. What is a primary key?**
A column (or combination of columns) whose value uniquely identifies each row,
and which may not be NULL. Here `candles` has the composite primary key
`(symbol, open_time)`: one row per trading pair per minute. PostgreSQL
implements a primary key with a unique index, so duplicates cannot exist.

**3. What is a foreign key?**
A column whose value must exist as a key in another table. `candles.symbol`
references `symbols.symbol`, so a candle can only exist for a pair that is
actually registered — and a symbol with candles cannot be deleted by accident.
This is the referential-integrity rule.

**4. Why are there two tables?**
To avoid repetition and inconsistency. The asset names (`BTC`, `USDT`,
"Bitcoin / Tether") belong to the pair, not to each of the 10,080 candles per
pair. Storing them once in `symbols` means a rename happens in one place, and the
foreign key guarantees the two tables agree. That is normalisation: each fact is
stored once.

**5. What is an index?**
An additional sorted data structure (a B-tree here) that lets the database jump
to matching rows instead of reading the whole table — like the index of a book
versus reading every page. `candles_pkey` indexes `(symbol, open_time)`, which is
exactly the column combination the chart queries filter on. Indexes cost storage
and slow down inserts, so unnecessary ones are avoided.

**6. What is SQL aggregation?**
Combining many rows into fewer, summarised rows — with functions like
`COUNT`, `SUM`, `MIN`, `MAX` and `AVG`, usually together with `GROUP BY`. Here,
15 one-minute rows become 1 fifteen-minute candle: total volume plus the extreme
and positional prices.

**7. How are OHLCV candles calculated from one-minute candles?**
Open = open of the earliest minute; High = `max(high)`; Low = `min(low)`;
Close = close of the latest minute; Volume = `sum(volume)`. The bucket itself is
created with `date_bin(INTERVAL '15 minutes', open_time, epoch)`, and `GROUP BY`
puts all rows of a bucket in one group.

**8. Why is the close *not* `MAX(close)`?**
Because close is a *positional* value, not an extreme: it is the price at the end
of the bucket. It can be lower than closes from earlier minutes — the last minute
of a rising-then-falling bucket may close below the maximum. `MAX(close)` would
report a price that was never the closing price. The same argument applies to
`MIN(open)`.

**9. How do you get the "first" and "last" value in SQL?**
By ordering inside the aggregate:
`(array_agg(open ORDER BY open_time ASC))[1]` collects the group's opens in
chronological order and takes the first; with `DESC` and `[1]` it takes the last
close. Ordering by the timestamp is what makes "first" and "last" well defined.

**10. Why is volume summed and not averaged?**
Volume is additive: the volume traded between 12:00 and 12:15 is the total traded
in each of those minutes. An average would answer a different question ("typical
volume per minute") and would be 15 times too small for a 15-minute candle.

**11. Why use PostgreSQL instead of TimescaleDB?**
TimescaleDB is PostgreSQL plus time-series machinery (hypertables, continuous
aggregates). It is useful at scale, but it would hide the very SQL this project
must demonstrate, and it is an extra extension to install. PostgreSQL alone has
everything needed here: `TIMESTAMPTZ`, `NUMERIC`, constraints, indexes and
`date_bin()` since version 14.

**12. Why is a WebSocket unnecessary?**
A WebSocket keeps a two-way connection open for *live* updates. This application
displays a fixed historical dataset that never changes between requests, so
ordinary HTTP GET requests return everything needed. A WebSocket would add
reconnection logic and non-reproducible state without improving the SQL
demonstration. Charts are redrawn only when the user changes something.

**13. What is SQL injection, and how is this project protected against it?**
SQL injection is an attack where user input is concatenated into SQL text so it
is executed as code (e.g. `' OR '1'='1`). Here, values are never concatenated:
they are passed as **bound parameters** (`%(symbol)s`) that PostgreSQL receives
separately from the statement, so they can only be values. The `interval` and
`range` parameters are validated against allowlists before use, and the only part
of the SQL that changes (the stride and bucket size) comes from hard-coded
definitions — never from the browser. There is no endpoint that executes
arbitrary SQL.

**14. What does the composite primary key `(symbol, open_time)` accomplish?**
Three things: (a) it makes duplicate minutes impossible — which is also what makes
re-running the importer safe; (b) it creates a unique B-tree index; (c) because
`symbol` is the leading column and `open_time` the second, that single index
serves `WHERE symbol = … AND open_time >= … AND open_time < …`, which is
precisely the chart query. Column order matters: an index on `(open_time, symbol)`
would not serve `WHERE symbol = …` as well.

**15. What happens when source minutes are missing?**
Nothing is invented. `HAVING count(*) = <bucket size>` keeps only buckets built
from all of their expected 1-minute rows, so an incomplete bucket is *not*
returned and the gap shows up as a gap in the chart. The importer also reports
missing minutes in the CSV files. Filling gaps by copying the previous price
would silently create data that never traded.

**16. Why is the default window anchored on the newest row instead of `now()`?**
Because the dataset is historical. `WHERE open_time >= now() - INTERVAL '24 hours'`
would match nothing today and the chart would be empty. Using
`window_end = first bucket boundary at or after max(open_time) + 1 minute` and
`window_start = window_end - 24 hours` (or 7 days) shows the newest data that
actually exists, and the dashboard displays that range and the last stored
timestamp so the user is never misled.

**17. What does `EXPLAIN` show?**
The query plan: which access methods PostgreSQL chose (sequential scan, index
scan, bitmap scan), in which order the operations run, how many rows it expects
at each step, and — with `ANALYZE` — how long each step really took and how many
rows it produced. It is the tool for checking whether an index is actually used.
The project includes one real plan; the important caveat is that plans depend on
data size, statistics, caching and planner settings, so a small table may
legitimately produce a sequential scan.

**18. Why is `NUMERIC` used for prices instead of `FLOAT`/`DOUBLE`?**
`NUMERIC` stores exact decimal values, while binary floating point cannot
represent most decimal fractions exactly and accumulates rounding error — a bad
property for money. Stored values come back exactly as they were imported. The
JSON sent to the browser uses ordinary numbers only because the charting library
plots floating point; that conversion is documented in the code and in this
README.

---

## Quick reference

```bash
docker compose up --build         # start everything (first run needs internet)
docker compose down               # stop (keep the data)
docker compose down -v            # stop and delete the database volume
docker compose exec backend pytest -v                     # run the 62 tests
docker compose exec backend python import_data.py         # re-import the CSVs (safe)
docker compose exec db psql -U crypto -d crypto_market_explorer   # psql prompt
```

Dashboard <http://localhost:5173> · API <http://localhost:8000/docs>
