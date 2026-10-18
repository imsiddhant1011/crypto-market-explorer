/**
 * Thin wrapper around the backend API.
 *
 * The base URL is baked in at build time (`VITE_API_BASE_URL`, see
 * frontend/Dockerfile). It defaults to the port the backend is published on.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, options)
  } catch (error) {
    if (error.name === 'AbortError') {
      throw error
    }
    throw new Error(
      `Cannot reach the API at ${API_BASE_URL}. Check that the backend is running ` +
        `(docker compose ps) and that this page is allowed to call it.`,
    )
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }
  return response.json()
}

/** Turn an error response into one readable sentence. */
async function readErrorMessage(response) {
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') {
      return body.detail
    }
    // FastAPI validation errors are a list of {loc, msg} objects.
    if (Array.isArray(body.detail)) {
      return body.detail.map((item) => item.msg).join('; ')
    }
  } catch {
    // The body was not JSON - fall back to the status code below.
  }
  return `The API answered with status ${response.status}.`
}

export function fetchSymbols(options = {}) {
  return request('/api/symbols', options)
}

export function fetchCandles({ symbol, interval, range, signal }) {
  const params = new URLSearchParams({ symbol, interval, range })
  return request(`/api/candles?${params.toString()}`, { signal })
}

export function fetchHealth(options = {}) {
  return request('/api/health', options)
}

export { API_BASE_URL }
