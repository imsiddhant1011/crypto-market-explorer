-- =============================================================================
--  Crypto Market Data Explorer - database schema
-- =============================================================================
--  This file is the single source of truth for the application schema.
--  It is applied by:
--    * the backend container on startup   (backend/app/init_db.py)
--    * the pytest fixtures for tests      (backend/tests/conftest.py)
--  It is written to be idempotent, so it can be executed any number of times.
--
--  Design notes
--  ------------
--  * Only two application tables exist: `symbols` and `candles`.
--  * One row in `candles` is one 1-minute candle. 5m / 15m / 30m candles are
--    NOT stored; they are calculated on the fly from these rows with SQL
--    (see backend/app/queries.py). The read-only `reporting` views at the end
--    of this file expose the same candles to Power BI for the DV deliverable.
--  * `open_time` is a TIMESTAMPTZ and always floor-aligned to a UTC minute.
--  * Prices and volume use NUMERIC, never floating point, so stored values are
--    exactly the values that were imported.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- symbols: the trading pairs the application knows about.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS symbols (
    symbol       VARCHAR(20)  PRIMARY KEY,
    base_asset   VARCHAR(10)  NOT NULL,
    quote_asset  VARCHAR(10)  NOT NULL,
    display_name VARCHAR(100) NOT NULL
);

-- -----------------------------------------------------------------------------
-- candles: one row per (symbol, 1-minute interval).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS candles (
    symbol    VARCHAR(20) NOT NULL,
    open_time TIMESTAMPTZ NOT NULL,
    open      NUMERIC     NOT NULL,
    high      NUMERIC     NOT NULL,
    low       NUMERIC     NOT NULL,
    close     NUMERIC     NOT NULL,
    volume    NUMERIC     NOT NULL,

    -- The composite primary key is what makes an import idempotent: the same
    -- (symbol, open_time) can never be stored twice. It also creates a B-tree
    -- index on (symbol, open_time) that serves the time-range queries.
    CONSTRAINT candles_pkey PRIMARY KEY (symbol, open_time),

    -- Every candle must belong to a known symbol.
    CONSTRAINT candles_symbol_fkey FOREIGN KEY (symbol) REFERENCES symbols (symbol),

    -- Prices are strictly positive.
    CONSTRAINT candles_open_positive  CHECK (open  > 0),
    CONSTRAINT candles_high_positive  CHECK (high  > 0),
    CONSTRAINT candles_low_positive   CHECK (low   > 0),
    CONSTRAINT candles_close_positive CHECK (close > 0),

    -- Traded volume can be zero but never negative.
    CONSTRAINT candles_volume_non_negative CHECK (volume >= 0),

    -- The high must be the highest price of the candle ...
    CONSTRAINT candles_high_is_highest CHECK (high >= open AND high >= close AND high >= low),

    -- ... and the low must be the lowest price of the candle.
    CONSTRAINT candles_low_is_lowest CHECK (low <= open AND low <= close AND low <= high)
);

-- -----------------------------------------------------------------------------
-- Seed data: the two supported trading pairs.
-- ON CONFLICT DO NOTHING keeps this idempotent and never rewrites existing rows.
-- -----------------------------------------------------------------------------
INSERT INTO symbols (symbol, base_asset, quote_asset, display_name)
VALUES
    ('BTCUSDT',  'BTC',  'USDT', 'Bitcoin / Tether'),
    ('ETHUSDT',  'ETH',  'USDT', 'Ether / Tether'),
    ('BNBUSDT',  'BNB',  'USDT', 'BNB / Tether'),
    ('SOLUSDT',  'SOL',  'USDT', 'Solana / Tether'),
    ('XRPUSDT',  'XRP',  'USDT', 'XRP / Tether'),
    ('ADAUSDT',  'ADA',  'USDT', 'Cardano / Tether'),
    ('DOGEUSDT', 'DOGE', 'USDT', 'Dogecoin / Tether')
ON CONFLICT (symbol) DO NOTHING;

-- -----------------------------------------------------------------------------
-- reporting: read-only views consumed by the Power BI dashboard (DV deliverable).
--
-- The application itself never reads these views; they exist so Power BI can
-- import one clean table per interval without repeating the aggregation in
-- Power Query. The 1-minute `candles` table remains the only stored data.
-- -----------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS reporting;

CREATE OR REPLACE VIEW reporting.candles_1m AS
SELECT
    symbol,
    '1m'::text AS interval,
    1 AS interval_minutes,
    open_time AS bucket_start,
    open,
    high,
    low,
    close,
    volume,
    1::bigint AS source_candles
FROM candles;

CREATE OR REPLACE VIEW reporting.candles_5m AS
WITH aggregated AS (
    SELECT
        symbol,
        date_bin(INTERVAL '5 minutes', open_time, TIMESTAMPTZ '1970-01-01 00:00:00+00') AS bucket_start,
        (array_agg(open ORDER BY open_time ASC))[1] AS open,
        max(high) AS high,
        min(low) AS low,
        (array_agg(close ORDER BY open_time DESC))[1] AS close,
        sum(volume) AS volume,
        count(*) AS source_candles
    FROM candles
    GROUP BY symbol, date_bin(INTERVAL '5 minutes', open_time, TIMESTAMPTZ '1970-01-01 00:00:00+00')
    HAVING count(*) = 5
)
SELECT
    symbol,
    '5m'::text AS interval,
    5 AS interval_minutes,
    bucket_start,
    open,
    high,
    low,
    close,
    volume,
    source_candles
FROM aggregated;

CREATE OR REPLACE VIEW reporting.candles_15m AS
WITH aggregated AS (
    SELECT
        symbol,
        date_bin(INTERVAL '15 minutes', open_time, TIMESTAMPTZ '1970-01-01 00:00:00+00') AS bucket_start,
        (array_agg(open ORDER BY open_time ASC))[1] AS open,
        max(high) AS high,
        min(low) AS low,
        (array_agg(close ORDER BY open_time DESC))[1] AS close,
        sum(volume) AS volume,
        count(*) AS source_candles
    FROM candles
    GROUP BY symbol, date_bin(INTERVAL '15 minutes', open_time, TIMESTAMPTZ '1970-01-01 00:00:00+00')
    HAVING count(*) = 15
)
SELECT
    symbol,
    '15m'::text AS interval,
    15 AS interval_minutes,
    bucket_start,
    open,
    high,
    low,
    close,
    volume,
    source_candles
FROM aggregated;

CREATE OR REPLACE VIEW reporting.candles_30m AS
WITH aggregated AS (
    SELECT
        symbol,
        date_bin(INTERVAL '30 minutes', open_time, TIMESTAMPTZ '1970-01-01 00:00:00+00') AS bucket_start,
        (array_agg(open ORDER BY open_time ASC))[1] AS open,
        max(high) AS high,
        min(low) AS low,
        (array_agg(close ORDER BY open_time DESC))[1] AS close,
        sum(volume) AS volume,
        count(*) AS source_candles
    FROM candles
    GROUP BY symbol, date_bin(INTERVAL '30 minutes', open_time, TIMESTAMPTZ '1970-01-01 00:00:00+00')
    HAVING count(*) = 30
)
SELECT
    symbol,
    '30m'::text AS interval,
    30 AS interval_minutes,
    bucket_start,
    open,
    high,
    low,
    close,
    volume,
    source_candles
FROM aggregated;

-- One table for Power BI: filter `interval` in the report to switch timeframe.
CREATE OR REPLACE VIEW reporting.candles AS
SELECT symbol, interval, interval_minutes, bucket_start, open, high, low, close, volume, source_candles
FROM reporting.candles_1m
UNION ALL
SELECT symbol, interval, interval_minutes, bucket_start, open, high, low, close, volume, source_candles
FROM reporting.candles_5m
UNION ALL
SELECT symbol, interval, interval_minutes, bucket_start, open, high, low, close, volume, source_candles
FROM reporting.candles_15m
UNION ALL
SELECT symbol, interval, interval_minutes, bucket_start, open, high, low, close, volume, source_candles
FROM reporting.candles_30m;

-- One complete UTC day per row (used for the month overview and return KPIs).
CREATE OR REPLACE VIEW reporting.daily_candles AS
WITH aggregated AS (
    SELECT
        symbol,
        date_bin(INTERVAL '1 day', open_time, TIMESTAMPTZ '1970-01-01 00:00:00+00') AS day_start,
        (array_agg(open ORDER BY open_time ASC))[1] AS open,
        max(high) AS high,
        min(low) AS low,
        (array_agg(close ORDER BY open_time DESC))[1] AS close,
        sum(volume) AS volume,
        count(*) AS source_candles
    FROM candles
    GROUP BY symbol, date_bin(INTERVAL '1 day', open_time, TIMESTAMPTZ '1970-01-01 00:00:00+00')
    HAVING count(*) = 1440
)
SELECT symbol, day_start, open, high, low, close, volume, source_candles
FROM aggregated;

-- Convenience views for Power BI cards and coverage tables.
CREATE OR REPLACE VIEW reporting.latest_prices AS
SELECT DISTINCT ON (symbol)
    symbol,
    open_time AS last_open_time,
    close AS last_close,
    volume AS last_minute_volume
FROM candles
ORDER BY symbol, open_time DESC;

CREATE OR REPLACE VIEW reporting.symbol_summary AS
SELECT
    symbol,
    min(open_time) AS first_open_time,
    max(open_time) AS last_open_time,
    count(*) AS candle_count
FROM candles
GROUP BY symbol;
