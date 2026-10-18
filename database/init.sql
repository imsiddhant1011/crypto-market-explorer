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
--    (see backend/app/queries.py).
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
    ('BTCUSDT', 'BTC', 'USDT', 'Bitcoin / Tether'),
    ('ETHUSDT', 'ETH', 'USDT', 'Ether / Tether')
ON CONFLICT (symbol) DO NOTHING;
