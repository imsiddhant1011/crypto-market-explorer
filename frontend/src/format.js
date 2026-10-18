/**
 * Small formatting helpers. Everything in this application is UTC.
 */

/** "2026-10-17T00:00:00Z" -> "2026-10-17 00:00 UTC" */
export function formatUtcTimestamp(isoString) {
  if (!isoString) {
    return 'n/a'
  }
  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) {
    return isoString
  }
  return `${date.toISOString().slice(0, 19).replace('T', ' ')} UTC`
}

/** Unix seconds (as sent by the API) -> "2026-10-17 00:00 UTC" */
export function formatUnixSecondsUtc(seconds) {
  if (seconds === null || seconds === undefined) {
    return 'n/a'
  }
  return formatUtcTimestamp(new Date(seconds * 1000).toISOString())
}

/**
 * Prices keep at most `digits` decimals; the database stores exactly what was
 * imported, so nothing is rounded before it reaches the browser.
 */
export function formatPrice(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 'n/a'
  }
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value)
}

/** Volumes can be very small, so they keep more decimals. */
export function formatVolume(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 'n/a'
  }
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 6,
  }).format(value)
}
