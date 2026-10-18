"""
FastAPI application - the HTTP layer of the Crypto Market Data Explorer.

Endpoints
---------
GET /api/symbols   supported trading pairs (read from PostgreSQL)
GET /api/candles   5m / 15m / 30m candles aggregated with SQL
GET /api/health    database connectivity check

Interactive API documentation is available at /docs while the server runs.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

import psycopg
from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from . import aggregation, database, queries

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("crypto_market_explorer")

# Explicit allowlists. The Literal types below give FastAPI validation for free
# (an unknown value is answered with HTTP 422 before any SQL is prepared), and
# the assertion guarantees the API never drifts from queries.INTERVALS/RANGES.
SUPPORTED_INTERVALS = ("5m", "15m", "30m")
SUPPORTED_RANGES = ("24h", "7d")
assert set(SUPPORTED_INTERVALS) == set(queries.INTERVALS), "interval allowlist out of sync"
assert set(SUPPORTED_RANGES) == set(queries.RANGES), "range allowlist out of sync"

DB_UNAVAILABLE_DETAIL = (
    "The database is not available. Check that PostgreSQL is running "
    "(docker compose ps) and try again."
)


def cors_origins() -> list[str]:
    """Origins allowed to call the API from a browser (see .env.example)."""
    raw = os.environ.get(
        "CORS_ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Open the connection pool on startup and close it on shutdown."""
    database.open_pool()
    logger.info("Connection pool ready for %s", database.redact(database.database_url()))
    yield
    database.close_pool()


app = FastAPI(
    title="Crypto Market Data Explorer API",
    description=(
        "Historical cryptocurrency candles aggregated from 1-minute source data "
        "with SQL. Educational project - the data is historical, not live."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Database failures become clean JSON errors (never a stack trace)
# ---------------------------------------------------------------------------


def _unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": DB_UNAVAILABLE_DETAIL},
    )


@app.exception_handler(PoolTimeout)
@app.exception_handler(psycopg.OperationalError)
async def handle_database_unavailable(request, exc):  # type: ignore[no-untyped-def]
    logger.warning("Database unavailable for %s: %s", request.url.path, exc.__class__.__name__)
    return _unavailable()


@app.exception_handler(psycopg.Error)
async def handle_database_error(request, exc):  # type: ignore[no-untyped-def]
    # Details are logged on the server, never returned to the browser.
    logger.error("Database error for %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "The database query failed. See the backend logs for details."},
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/")
def get_root() -> dict:
    """Tiny landing response so http://localhost:8000 is not a 404."""
    return {
        "name": "Crypto Market Data Explorer API",
        "data": "historical (not live)",
        "endpoints": ["/api/symbols", "/api/candles?symbol=BTCUSDT&interval=15m&range=24h", "/api/health"],
        "documentation": "/docs",
    }


@app.get("/api/symbols")
def get_symbols() -> dict:
    """The trading pairs the imported dataset contains."""
    return {"symbols": aggregation.list_symbols()}


@app.get("/api/candles")
def get_candles(
    symbol: str = Query(
        ...,
        min_length=2,
        max_length=20,
        description="Trading pair, for example BTCUSDT",
        examples=["BTCUSDT"],
    ),
    interval: Literal["5m", "15m", "30m"] = Query(  # type: ignore[assignment]
        queries.DEFAULT_INTERVAL,
        description="Candle size. Aggregated from 1-minute data with SQL.",
    ),
    range_name: Literal["24h", "7d"] = Query(  # type: ignore[assignment]
        queries.DEFAULT_RANGE,
        alias="range",
        description="Historical range, measured back from the newest imported candle.",
    ),
) -> dict:
    """
    Candles for one symbol, aggregated by PostgreSQL, plus the SQL explanation.

    The window is anchored on the newest imported candle (not on the current
    clock), so the application works offline with historical data.
    """
    try:
        return aggregation.build_candles_response(
            symbol=symbol, interval_name=interval, range_name=range_name
        )
    except aggregation.UnknownSymbolError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/api/health")
def get_health(response: Response) -> dict:
    """Report whether the backend can talk to PostgreSQL."""
    try:
        return aggregation.check_database()
    except (PoolTimeout, psycopg.Error) as exc:
        logger.warning("Health check failed: %s", exc.__class__.__name__)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "error",
            "database": "unreachable",
            "detail": DB_UNAVAILABLE_DETAIL,
        }
