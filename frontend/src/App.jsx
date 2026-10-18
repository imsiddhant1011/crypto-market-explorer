import { useCallback, useEffect, useMemo, useState } from 'react'

import { fetchCandles, fetchSymbols } from './api'
import CandlestickChart from './components/CandlestickChart'
import CandleDetails from './components/CandleDetails'
import MarketSelector from './components/MarketSelector'
import SqlEducationPanel from './components/SqlEducationPanel'
import VolumeChart from './components/VolumeChart'
import { formatUtcTimestamp } from './format'

const DEFAULT_TIMEFRAME = '15m'
const DEFAULT_RANGE = '24h'

export default function App() {
  const [symbols, setSymbols] = useState([])
  const [symbol, setSymbol] = useState('')
  const [timeframe, setTimeframe] = useState(DEFAULT_TIMEFRAME)
  const [range, setRange] = useState(DEFAULT_RANGE)

  const [payload, setPayload] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)

  const [selectedCandle, setSelectedCandle] = useState(null)
  const [charts, setCharts] = useState({ price: null, volume: null })

  // ---------------------------------------------------------------------------
  // 1. The trading pairs, read from PostgreSQL through the API.
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const controller = new AbortController()

    fetchSymbols({ signal: controller.signal })
      .then((response) => {
        setSymbols(response.symbols)
        setSymbol((current) => current || response.symbols[0]?.symbol || '')
      })
      .catch((requestError) => {
        if (requestError.name !== 'AbortError') {
          setError(requestError.message)
          setLoading(false)
        }
      })

    return () => controller.abort()
  }, [reloadKey])

  // ---------------------------------------------------------------------------
  // 2. Candles and the SQL explanation for the current selection.
  //    Changing the pair, the timeframe or the range always reloads from the API
  //    and clears the previously selected candle.
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (!symbol) {
      return undefined
    }

    const controller = new AbortController()
    setLoading(true)
    setError(null)
    setSelectedCandle(null)

    fetchCandles({ symbol, interval: timeframe, range, signal: controller.signal })
      .then((response) => {
        setPayload(response)
        setLoading(false)
      })
      .catch((requestError) => {
        if (requestError.name === 'AbortError') {
          return
        }
        setPayload(null)
        setError(requestError.message)
        setLoading(false)
      })

    return () => controller.abort()
  }, [symbol, timeframe, range, reloadKey])

  // ---------------------------------------------------------------------------
  // 3. Keep the candlestick chart and the volume chart on the same time range,
  //    so zooming, scrolling or refitting one of them moves both.
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const { price, volume } = charts
    if (!price || !volume) {
      return undefined
    }

    const EPSILON = 0.001

    const shareRange = (from, to) => (visibleRange) => {
      if (!visibleRange) {
        return
      }
      const current = to.timeScale().getVisibleLogicalRange()
      if (
        current &&
        Math.abs(current.from - visibleRange.from) < EPSILON &&
        Math.abs(current.to - visibleRange.to) < EPSILON
      ) {
        // Already showing this range - this is also what stops the two charts
        // from echoing the change back and forth.
        return
      }
      to.timeScale().setVisibleLogicalRange(visibleRange)
    }

    const fromPrice = shareRange(price, volume)
    const fromVolume = shareRange(volume, price)
    price.timeScale().subscribeVisibleLogicalRangeChange(fromPrice)
    volume.timeScale().subscribeVisibleLogicalRangeChange(fromVolume)

    return () => {
      // A chart that was already disposed has removed its subscriptions itself.
      try {
        price.timeScale().unsubscribeVisibleLogicalRangeChange(fromPrice)
        volume.timeScale().unsubscribeVisibleLogicalRangeChange(fromVolume)
      } catch {
        // Nothing left to unsubscribe.
      }
    }
  }, [charts.price, charts.volume])

  const handleChartReady = useCallback(
    (which) => (chart) => {
      setCharts((previous) =>
        previous[which] === chart ? previous : { ...previous, [which]: chart },
      )
    },
    [],
  )

  // While loading (or after an error) the charts are emptied, so no candle from
  // the previous selection stays on screen.
  const candles = useMemo(
    () => (payload && !loading && !error ? payload.candles : []),
    [payload, loading, error],
  )

  const isEmpty = !loading && !error && payload && payload.candle_count === 0

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>Crypto Market Data Explorer</h1>
          <p className="subtitle">
            Historical 1-minute candlesticks stored in PostgreSQL and aggregated to 5m /
            15m / 30m candles with SQL. This is an educational DBMS project: the data is
            historical, it is not a live price feed, and nothing can be traded here.
          </p>
        </div>
        <span className="history-badge">Historical dataset · UTC</span>
      </header>

      <main className="layout">
        <section className="chart-column">
          <MarketSelector
            symbols={symbols}
            symbol={symbol}
            onSymbolChange={setSymbol}
            timeframe={timeframe}
            onTimeframeChange={setTimeframe}
            range={range}
            onRangeChange={setRange}
            disabled={loading}
          />

          <div className="panel chart-panel">
            <div className="chart-head">
              <h2>
                {payload ? `${payload.display_name} · ${payload.interval} candles` : 'Candles'}
              </h2>
              <span className="muted small">Time axis and timestamps in UTC</span>
            </div>

            {error && (
              <div className="state error" role="alert">
                <strong>Could not load the chart.</strong>
                <p>{error}</p>
                <button type="button" onClick={() => setReloadKey((key) => key + 1)}>
                  Try again
                </button>
              </div>
            )}

            {loading && !error && <div className="state">Loading candles from the API…</div>}

            {isEmpty && (
              <div className="state">
                <strong>No complete {timeframe} candles in this range.</strong>
                <p>
                  PostgreSQL only returns a candle when all{' '}
                  {payload.interval_minutes} expected 1-minute rows of the bucket are
                  present, so an empty result means the source data has gaps here.
                  Nothing is filled in with invented prices.
                </p>
                <p>
                  {payload.dataset_last_timestamp
                    ? `Imported data covers ${formatUtcTimestamp(
                        payload.dataset_first_timestamp,
                      )} → ${formatUtcTimestamp(payload.dataset_last_timestamp)}.`
                    : 'No 1-minute candles have been imported for this symbol yet.'}
                </p>
              </div>
            )}

            <div className={candles.length === 0 ? 'chart-holder chart-holder-empty' : 'chart-holder'}>
              <CandlestickChart
                candles={candles}
                onSelectCandle={setSelectedCandle}
                onChartReady={handleChartReady('price')}
              />
              <VolumeChart candles={candles} onChartReady={handleChartReady('volume')} />
            </div>

            {payload && !error && payload.candle_count > 0 && (
              <div className="chart-meta">
                <div>
                  <dt>Chart window</dt>
                  <dd>
                    {formatUtcTimestamp(payload.window_start)} →{' '}
                    {formatUtcTimestamp(payload.window_end)}
                  </dd>
                </div>
                <div>
                  <dt>Candles in view</dt>
                  <dd>
                    {payload.candle_count} × {payload.interval} ({payload.range_label})
                  </dd>
                </div>
                <div>
                  <dt>Last 1-minute candle in the database</dt>
                  <dd>{formatUtcTimestamp(payload.dataset_last_timestamp)}</dd>
                </div>
                <div>
                  <dt>Imported data covers</dt>
                  <dd>
                    {formatUtcTimestamp(payload.dataset_first_timestamp)} →{' '}
                    {formatUtcTimestamp(payload.dataset_last_timestamp)}
                  </dd>
                </div>
                <p className="muted small meta-note">
                  The window is anchored on the newest imported candle, not on the computer
                  clock, and it ends where the next bucket would start. Each{' '}
                  {payload.interval} candle is built from{' '}
                  {payload.source_candles_per_bucket} stored 1-minute candles.
                </p>
              </div>
            )}
          </div>

          <CandleDetails
            candle={selectedCandle}
            timeframe={timeframe}
            baseAsset={payload?.base_asset ?? ''}
          />
        </section>

        <section className="education-column">
          <SqlEducationPanel education={payload?.education} loading={loading} />
        </section>
      </main>
    </div>
  )
}
