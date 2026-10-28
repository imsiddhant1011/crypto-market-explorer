/**
 * Trading-pair dropdown plus the timeframe and historical-range buttons.
 */

const TIMEFRAMES = ['5m', '15m', '30m']

const RANGES = [
  { value: '1d', label: '1 day' },
  { value: '1w', label: '1 week' },
  { value: '1m', label: '1 month' },
]

export default function MarketSelector({
  symbols,
  symbol,
  onSymbolChange,
  timeframe,
  onTimeframeChange,
  range,
  onRangeChange,
  disabled,
}) {
  return (
    <div className="controls">
      <label className="control">
        <span className="control-label">Trading pair</span>
        <select
          className="pair-select"
          value={symbol}
          onChange={(event) => onSymbolChange(event.target.value)}
          disabled={disabled || symbols.length === 0}
        >
          {symbols.length === 0 && <option value="">Loading pairs…</option>}
          {symbols.map((item) => (
            <option key={item.symbol} value={item.symbol}>
              {item.display_name} ({item.symbol})
            </option>
          ))}
        </select>
      </label>

      <div className="control">
        <span className="control-label">Timeframe</span>
        <div className="segmented" role="group" aria-label="Timeframe">
          {TIMEFRAMES.map((value) => (
            <button
              key={value}
              type="button"
              className={value === timeframe ? 'segment active' : 'segment'}
              aria-pressed={value === timeframe}
              onClick={() => onTimeframeChange(value)}
            >
              {value}
            </button>
          ))}
        </div>
      </div>

      <div className="control">
        <span className="control-label">Historical range</span>
        <div className="segmented" role="group" aria-label="Historical range">
          {RANGES.map((item) => (
            <button
              key={item.value}
              type="button"
              className={item.value === range ? 'segment active' : 'segment'}
              aria-pressed={item.value === range}
              onClick={() => onRangeChange(item.value)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
