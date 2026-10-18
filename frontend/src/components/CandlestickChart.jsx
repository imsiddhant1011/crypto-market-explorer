import { useEffect, useRef } from 'react'
import { CandlestickSeries, CrosshairMode, createChart } from 'lightweight-charts'

/**
 * The candlestick chart (upper chart).
 *
 * * real OHLC candles from the API - nothing is simulated on the client;
 * * green when close >= open, red when close < open (Lightweight Charts uses
 *   exactly that rule internally);
 * * the time axis is hidden here because the volume chart right below owns it;
 * * clicking a candle reports the selected candle to the parent component.
 */

// Both charts reserve the same width for their price scale, so the plot areas
// of the price chart and the volume chart line up perfectly.
export const PRICE_SCALE_WIDTH = 78

export default function CandlestickChart({ candles, onSelectCandle, onChartReady }) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)

  // The click handler and the "chart is ready" callback are read through refs,
  // so the chart is created exactly once instead of on every render.
  const candlesRef = useRef(candles)
  const selectRef = useRef(onSelectCandle)
  const readyRef = useRef(onChartReady)

  useEffect(() => {
    selectRef.current = onSelectCandle
  }, [onSelectCandle])

  useEffect(() => {
    readyRef.current = onChartReady
  }, [onChartReady])

  useEffect(() => {
    const container = containerRef.current
    if (!container) {
      return undefined
    }

    const chart = createChart(container, {
      autoSize: true, // the chart follows the size of its container
      layout: {
        background: { color: '#ffffff' },
        textColor: '#475569',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#f1f5f9' },
        horzLines: { color: '#f1f5f9' },
      },
      rightPriceScale: { minimumWidth: PRICE_SCALE_WIDTH, borderColor: '#e2e8f0' },
      timeScale: { visible: false, timeVisible: true, secondsVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
    })

    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#16a34a',
      downColor: '#dc2626',
      wickUpColor: '#16a34a',
      wickDownColor: '#dc2626',
      borderVisible: false,
    })

    const handleClick = (parameter) => {
      if (parameter.time === undefined || !selectRef.current) {
        return
      }
      const candle = candlesRef.current.find((item) => item.time === parameter.time)
      if (candle) {
        selectRef.current(candle)
      }
    }
    chart.subscribeClick(handleClick)

    chartRef.current = chart
    seriesRef.current = series
    if (readyRef.current) {
      readyRef.current(chart)
    }

    // Cleanup: remove the subscription and dispose of the chart itself.
    return () => {
      chart.unsubscribeClick(handleClick)
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      if (readyRef.current) {
        readyRef.current(null)
      }
    }
  }, [])

  useEffect(() => {
    const series = seriesRef.current
    const chart = chartRef.current
    candlesRef.current = candles
    if (!series || !chart) {
      return
    }
    series.setData(
      candles.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })),
    )
    if (candles.length > 0) {
      chart.timeScale().fitContent()
    }
  }, [candles])

  return <div className="price-chart" ref={containerRef} />
}
