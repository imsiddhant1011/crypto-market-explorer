#!/bin/sh
# =============================================================================
#  Backend container entrypoint.
#
#  Startup order (every step is safe to repeat):
#    1. wait for PostgreSQL and create/verify the schema + symbol seed rows
#    2. import the bundled CSV files (duplicates are skipped)
#    3. start the API server
# =============================================================================
set -e

echo "[start] Initialising database schema ..."
python -m app.init_db

echo "[start] Importing historical CSV data ..."
python import_data.py

echo "[start] Starting the API on http://0.0.0.0:8000 ..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
