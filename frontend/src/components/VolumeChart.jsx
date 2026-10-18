import { useEffect, useRef } from 'react'
import { HistogramSeries, createChart } from 'lightweight-charts'

import { PRICE_SCALE_WIDTH } from './CandlestickChart.jsx'

/**
 * The volume histogram (lower chart).
 *
 * It uses the same timestamps as the candlestick chart - the same candles array
 * - and is kept in sync with it by the parent component (App.jsx), which shares
 * the visible time range between the two charts.
 *
 * Columns are tinted green/red to match the direction of the candle.
 */

const UP_COLOR = 'rgba(22, 163, 74, 0.45)'
const DOWN_COLOR = 'rgba(220, 38, 38, 0.45)'

export function volumeBar(candle) {
  const rising = candle.close >= candle.open
  return {
    time: candle.time,
    value: candle.volume,
    color: rising ? UP_COLOR : DOWN_COLOR,
  }
}

export default function VolumeChart({ candles, onChartReady }) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const candlesRef = useRef(candles)
  const readyRef = useRef(onChartReady)

  useEffect(() => {
    readyRef.current = onChartReady
  }, [onChartReady])

  useEffect(() => {
    const container = containerRef.current
    if (!container) {
      return undefined
    }

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { color: '#ffffff' },
        textColor: '#475569',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#f1f5f9' },
        horzLines: { color: '#f1f5f9' },
      },
      // Same width as the candlestick chart -> aligned plot areas.
      rightPriceScale: { minimumWidth: PRICE_SCALE_WIDTH, borderColor: '#e2e8f0' },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: '#e2e8f0' },
      crosshair: { horzLine: { visible: false, labelVisible: false } },
    })

    const series = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceLineVisible: false,
      lastValueVisible: false,
    })

    chartRef.current = chart
    seriesRef.current = series
    if (readyRef.current) {
      readyRef.current(chart)
    }

    // Cleanup: dispose of the chart and everything subscribed to it.
    return () => {
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
    series.setData(candles.map(volumeBar))
    if (candles.length > 0) {
      chart.timeScale().fitContent()
    }
  }, [candles])

  return <div className="volume-chart" ref={containerRef} />
}
