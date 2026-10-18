import { formatPrice, formatUnixSecondsUtc, formatVolume } from '../format.js'

/**
 * Details of the candle the user clicked in the chart.
 *
 * The parent clears the selection whenever the pair, timeframe or range
 * changes, so a stale candle is never shown.
 */
export default function CandleDetails({ candle, timeframe, baseAsset }) {
  if (!candle) {
    return (
      <section className="panel details">
        <h2>Selected candle</h2>
        <p className="muted">
          Click a candle in the chart to see its values. The selection is cleared when you
          change the trading pair, the timeframe or the range.
        </p>
      </section>
    )
  }

  const change = candle.close - candle.open
  const changePercent = candle.open === 0 ? 0 : (change / candle.open) * 100
  const rising = candle.close >= candle.open

  return (
    <section className="panel details">
      <div className="details-head">
        <h2>Selected candle</h2>
        <span className={rising ? 'tag up' : 'tag down'}>
          {rising ? 'close >= open' : 'close < open'}
        </span>
      </div>

      <dl className="details-grid">
        <div>
          <dt>Timestamp (UTC)</dt>
          <dd>{formatUnixSecondsUtc(candle.time)}</dd>
        </div>
        <div>
          <dt>Interval</dt>
          <dd>{timeframe}</dd>
        </div>
        <div>
          <dt>Open</dt>
          <dd className="number">{formatPrice(candle.open)}</dd>
        </div>
        <div>
          <dt>High</dt>
          <dd className="number">{formatPrice(candle.high)}</dd>
        </div>
        <div>
          <dt>Low</dt>
          <dd className="number">{formatPrice(candle.low)}</dd>
        </div>
        <div>
          <dt>Close</dt>
          <dd className="number">{formatPrice(candle.close)}</dd>
        </div>
        <div>
          <dt>Volume</dt>
          <dd className="number">
            {formatVolume(candle.volume)} {baseAsset}
          </dd>
        </div>
        <div>
          <dt>Close − Open</dt>
          <dd className="number">
            {change >= 0 ? '+' : ''}
            {formatPrice(change)} ({changePercent >= 0 ? '+' : ''}
            {changePercent.toFixed(2)}%)
          </dd>
        </div>
      </dl>
    </section>
  )
}
