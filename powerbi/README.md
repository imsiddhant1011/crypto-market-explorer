# Power BI dashboard (DV deliverable)

This folder contains everything needed to build the **data-visualisation**
component of the project in Power BI. Power BI connects directly to the
PostgreSQL database used by the web application; it does **not** call the FastAPI
backend, and no Python visualisation code is involved.

The database contains 30 days (2026-09-28 → 2026-10-27) of 1-minute candles for
seven pairs: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT and DOGEUSDT.

```
Power BI Desktop ── PostgreSQL (Import) ──► reporting.candles / reporting.daily_candles
```

---

## 1. Files in this folder

| File | Purpose |
| --- | --- |
| `crypto-market-explorer.pbids` | Double-click to open Power BI Desktop with the PostgreSQL connection pre-filled (Windows). |
| `powerquery.m` | Power Query (M) queries for the five tables. Paste each one into **Advanced Editor** if you prefer not to use the Navigator. |
| `measures.dax` | DAX measures for the KPI cards and comparison page. |
| `theme.json` | Report colour theme (green/red candles, slate text, sky-blue accent). |

---

## 2. Start the database

From the repository root:

```bash
docker compose up -d db backend
```

The backend imports the CSVs on startup. Wait until this returns `status: ok`:

```bash
curl http://localhost:8000/api/health
```

The database is then available on the host at `localhost:5432`:

| Setting | Value |
| --- | --- |
| Server | `localhost:5432` |
| Database | `crypto_market_explorer` |
| User | `crypto` |
| Password | `crypto_dev_password` |
| SSL | off (local Docker only) |

These are the local development values from `.env.example`; change them in
`.env` if you use different credentials.

---

## 3. Connect Power BI

### Option A — connection file

On Windows, double-click `crypto-market-explorer.pbids`. Power BI Desktop opens
the PostgreSQL connector with the server and database filled in. Choose
**Import** and click **OK**, then enter the credentials above.

If your Power BI version does not recognise the file, use Option B.

### Option B — Get Data

1. **Home → Get Data → More… → Database → PostgreSQL database**.
2. Server: `localhost:5432`; Database: `crypto_market_explorer`.
3. Data Connectivity mode: **Import** (recommended).
4. Credentials: **Database** tab → user `crypto`, password `crypto_dev_password`.

> If Power BI asks for the Npgsql provider, install the 64-bit Npgsql provider
> and restart Power BI Desktop. Recent Power BI Desktop versions include it.

---

## 4. Load the five tables

In the Navigator, expand the `reporting` schema and select:

| Query name | Source | Grain |
| --- | --- | --- |
| `Symbols` | `public.symbols` | one row per pair |
| `Candles` | `reporting.candles` | one row per pair / interval / bucket |
| `DailyCandles` | `reporting.daily_candles` | one row per pair / complete UTC day |
| `LatestPrices` | `reporting.latest_prices` | one row per pair |
| `SymbolSummary` | `reporting.symbol_summary` | one row per pair (coverage) |

Rename the queries exactly as shown — the DAX file uses these names. If you
prefer to paste the queries manually, `powerquery.m` contains them all.

`reporting.candles` includes four intervals in one table:

| `interval` | `interval_minutes` | Rows per pair (30 days) |
| --- | --- | --- |
| `1m` | 1 | 43,200 |
| `5m` | 5 | 8,640 |
| `15m` | 15 | 2,880 |
| `30m` | 30 | 1,440 |

For the one-month view prefer **15m or 30m**; 1m is available but makes the
candlestick visual unnecessarily heavy.

---

## 5. Data model

Create these relationships in **Model view** (all single-direction, `Symbols` on
the one side):

```
Symbols[1] ──< Candles[*]
Symbols[1] ──< DailyCandles[*]
Symbols[1] ──< LatestPrices[*]
Symbols[1] ──< SymbolSummary[*]
```

Then:

1. Select `Candles[interval]` → **Column tools → Sort by column →
   `interval_minutes`**, so the slicer shows 1m, 5m, 15m, 30m in that order.
2. Hide the `symbol` key columns in `Candles`, `DailyCandles`, `LatestPrices`
   and `SymbolSummary` (the `Symbols` dimension owns the labels).
3. Do **not** create a relationship between `Candles` and `DailyCandles`; they
   are alternative grains of the same fact table.
4. Optional: add a calculated column `Date = Candles[bucket_start].[Date]` and
   mark a small calendar table as a date table if you want regular date
   hierarchies.

---

## 6. Report layout

### Page 1 — Market overview

Suggested canvas: 16:9 (1280 × 720). Header: `Crypto Market Data Explorer ·
September–October 2026 · UTC`.

| Visual | Fields |
| --- | --- |
| Pair slicer | `Symbols[display_name]`, dropdown, **single select** |
| Timeframe slicer | `Candles[interval]`, tile buttons, **single select** |
| Date range slicer | `Candles[bucket_start]`, **Between** 2026-09-28 and 2026-10-27 |
| KPI cards | `Latest Close`, `Period Return %`, `Period High`, `Period Low`, `Period Volume` |
| Candlestick | `bucket_start` (axis), `open`, `high`, `low`, `close`, `volume` |
| Volume chart | `bucket_start` (axis), `volume` (columns), colored by close ≥ open |
| Month trend | `DailyCandles[day_start]` (axis), `DailyCandles[close]` (line) |

> A **relative-date** slicer uses today's date. Because this dataset ends on
> 2026-10-27, use **Between** with the dataset dates for a reproducible demo.

#### 1 day / 1 week / 1 month buttons

The React dashboard has three range buttons. Reproduce them in Power BI with
**bookmarks** on the date-range slicer:

1. Keep `Candles[bucket_start]` on the page as a **Between** slicer.
2. Set it to **2026-10-27 → 2026-10-27** and add a bookmark named `1 day`.
3. Set it to **2026-10-21 → 2026-10-27** and add a bookmark named `1 week`.
4. Set it to **2026-09-28 → 2026-10-27** and add a bookmark named `1 month`.
5. Insert three buttons (**Insert → Buttons → Blank**) labelled `1 day`,
   `1 week`, `1 month`, and set **Action → Type: Bookmark** to the matching
   bookmark.

When creating each bookmark, keep **Data** selected (it stores the slicer
state) and **Display** selected (it stores the visible page state). The result is
the same one-click range switch as the web dashboard, with all three ranges
defined once for the whole report.

### Page 2 — Compare pairs

| Visual | Fields |
| --- | --- |
| Timeframe slicer | `Candles[interval]`, single select |
| Date range slicer | `Candles[bucket_start]`, Between |
| Daily return lines | `DailyCandles[day_start]` (axis), `Daily Return %` (values), legend `Symbols[display_name]` |
| Comparison table | `Symbols[display_name]`, `Latest Close`, `Period Return %`, `30-Day High`, `30-Day Low`, `Average Daily Volume` |
| Volume columns | `Symbols[display_name]` (axis), `Period Volume` (values) |

### Page 3 — Data quality / coverage

| Visual | Fields |
| --- | --- |
| Cards | `COUNTROWS(Candles)` (all rows), `Days Covered`, `Selected Pair` |
| Coverage table | `SymbolSummary` — symbol, first and last timestamp, candle count |
| Bar chart | `SymbolSummary[symbol]` (axis), `candle_count` (values) |
| Slicer | `Candles[interval]`, to show that each interval has the expected count |

Expected counts for the full dataset:

| Interval | Rows (all 7 pairs) |
| --- | --- |
| 1m | 302,400 |
| 5m | 60,480 |
| 15m | 20,160 |
| 30m | 10,080 |
| Daily | 210 |

If a count is lower, the source data has a gap or the views are being filtered
by a stale slicer — the views only return **complete** buckets.

---

## 7. Candlestick visual

Power BI has no built-in candlestick visual. Install one from AppSource:

1. **Visualizations pane → Get more visuals**.
2. Search for **Candlestick** (for example *Candlestick by MAQ Software*).
3. Add the visual and map:
   * **Axis / Category**: `Candles[bucket_start]`
   * **Open**: `Candles[open]`
   * **High**: `Candles[high]`
   * **Low**: `Candles[low]`
   * **Close**: `Candles[close]`
   * **Volume** (if the visual offers it): `Candles[volume]`
   * **Tooltip**: `Symbols[display_name]`, `Candles[interval]`

Make the timeframe slicer single-select; otherwise two intervals overlap at the
same timestamp and the visual cannot draw one candle per bucket.

If custom visuals are not allowed in your environment, use a **Line and
clustered column chart**: line = `close`, columns = `volume`, axis =
`bucket_start`. It is less decorative but uses only native visuals and tells the
same story.

---

## 8. DAX measures

Open `measures.dax` and create each measure with **Modeling → New measure**.
The important ones:

| Measure | Used for |
| --- | --- |
| `Latest Close` | KPI card; requires one selected pair |
| `Period High` / `Period Low` | KPI cards |
| `Period Volume` | KPI card / volume comparison |
| `Candle Count` | data-quality cards |
| `Period Return %` | first open → last close of the selection |
| `Daily Return %` | line chart on the comparison page |
| `30-Day High` / `30-Day Low` | month cards |
| `Days Covered` | coverage card |
| `Average Daily Volume` | comparison table |

Keep the symbol and interval slicers in **single-select** mode for the candle
page. `Period Return %` is defined as the first open and the last close of the
current selection, which is only meaningful for one symbol and one interval at a
time. If you need a multi-symbol return, duplicate the measure and use
`ALLEXCEPT(Symbols, Symbols[symbol])`.

---

## 9. Theme

**View → Themes → Browse for themes** and choose `theme.json`. It sets the
green/red candle palette, slate text and a sky-blue table accent. You can still
override individual visuals afterwards.

---

## 10. Refresh workflow

The report uses **Import** mode, so Power BI stores a snapshot:

* after `docker compose up` finishes importing, press **Refresh** in Power BI
  Desktop;
* after replacing the CSV files or resetting the database, refresh all tables;
* if you change `POSTGRES_PORT` in `.env`, edit the PostgreSQL source in
  **Transform data → Data source settings**.

DirectQuery also works, but the `reporting.candles` view aggregates 302,400
source rows per query; Import is faster for a classroom demo.

---

## 11. macOS note

Power BI Desktop is Windows-only. On macOS you have three options:

1. run Power BI Desktop in a Windows VM (Parallels/UTM/VMware) and connect to
   `localhost:5432` (the Docker port is published on the Mac host);
2. use **Power BI Service** in a browser and an on-premises data gateway to
   reach the local PostgreSQL;
3. use the React dashboard for the live demo and submit the Power BI report
   built on a Windows machine.

The database, the views and the `.pbids`/M/DAX files are OS-independent.

---

## 12. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `The server was not found` / connection refused | `docker compose ps` — is `db` healthy? Is port 5432 published? |
| Password authentication failed | Use the values in `.env` / `.env.example`; the default is `crypto` / `crypto_dev_password`. |
| Navigator shows no `reporting` schema | The backend has not applied `database/init.sql` yet. Run `docker compose up -d backend` and check `docker compose logs backend`; or apply `database/init.sql` manually with `psql`. |
| Candlestick is empty | The timeframe slicer has multiple intervals selected, or the date slicer excludes the bucket. Select one interval and a date range inside 2026-09-28–2026-10-27. |
| Times look shifted | The database stores UTC. Set the report/page timezone to UTC, or convert the timestamp explicitly; do not assume the local Windows timezone. |
| 1m view is slow | Use 15m or 30m for the month view; 1m is 302,400 rows. |
| Custom visual missing | Use the native line + column fallback, or ask the instructor to allow AppSource visuals. |

For the database/API background and the viva questions, see the main
[`README.md`](../README.md).
