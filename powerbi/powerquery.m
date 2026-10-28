// Power Query (M) queries for the Crypto Market Data Explorer report.
//
// In Power BI Desktop: Home -> Transform data -> Advanced Editor, paste one
// query at a time and rename it exactly as shown. The PostgreSQL server is the
// host port published by docker-compose.yml (localhost:5432 by default).
//
// Load these five queries:
//   Symbols        (dimension)
//   Candles        (fact: 1m / 5m / 15m / 30m)
//   DailyCandles   (fact: one row per complete UTC day)
//   LatestPrices   (one row per symbol, for KPI cards)
//   SymbolSummary  (coverage table for the data-quality page)

// ---------------------------------------------------------------------------
// Symbols
// ---------------------------------------------------------------------------
let
    Source = PostgreSQL.Database("localhost:5432", "crypto_market_explorer"),
    Data = Source{[Schema = "public", Item = "symbols"]}[Data],
    ChangedTypes = Table.TransformColumnTypes(
        Data,
        {
            {"symbol", type text},
            {"base_asset", type text},
            {"quote_asset", type text},
            {"display_name", type text}
        }
    )
in
    ChangedTypes

// ---------------------------------------------------------------------------
// Candles
// ---------------------------------------------------------------------------
let
    Source = PostgreSQL.Database("localhost:5432", "crypto_market_explorer"),
    Data = Source{[Schema = "reporting", Item = "candles"]}[Data],
    ChangedTypes = Table.TransformColumnTypes(
        Data,
        {
            {"symbol", type text},
            {"interval", type text},
            {"interval_minutes", Int64.Type},
            {"bucket_start", type datetimezone},
            {"open", type number},
            {"high", type number},
            {"low", type number},
            {"close", type number},
            {"volume", type number},
            {"source_candles", Int64.Type}
        }
    )
in
    ChangedTypes

// ---------------------------------------------------------------------------
// DailyCandles
// ---------------------------------------------------------------------------
let
    Source = PostgreSQL.Database("localhost:5432", "crypto_market_explorer"),
    Data = Source{[Schema = "reporting", Item = "daily_candles"]}[Data],
    ChangedTypes = Table.TransformColumnTypes(
        Data,
        {
            {"symbol", type text},
            {"day_start", type datetimezone},
            {"open", type number},
            {"high", type number},
            {"low", type number},
            {"close", type number},
            {"volume", type number},
            {"source_candles", Int64.Type}
        }
    )
in
    ChangedTypes

// ---------------------------------------------------------------------------
// LatestPrices
// ---------------------------------------------------------------------------
let
    Source = PostgreSQL.Database("localhost:5432", "crypto_market_explorer"),
    Data = Source{[Schema = "reporting", Item = "latest_prices"]}[Data],
    ChangedTypes = Table.TransformColumnTypes(
        Data,
        {
            {"symbol", type text},
            {"last_open_time", type datetimezone},
            {"last_close", type number},
            {"last_minute_volume", type number}
        }
    )
in
    ChangedTypes

// ---------------------------------------------------------------------------
// SymbolSummary
// ---------------------------------------------------------------------------
let
    Source = PostgreSQL.Database("localhost:5432", "crypto_market_explorer"),
    Data = Source{[Schema = "reporting", Item = "symbol_summary"]}[Data],
    ChangedTypes = Table.TransformColumnTypes(
        Data,
        {
            {"symbol", type text},
            {"first_open_time", type datetimezone},
            {"last_open_time", type datetimezone},
            {"candle_count", Int64.Type}
        }
    )
in
    ChangedTypes
