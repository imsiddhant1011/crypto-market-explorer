#!/bin/sh
# =============================================================================
#  Runs once, when the PostgreSQL container initialises an empty data volume
#  (files in /docker-entrypoint-initdb.d).
#
#  It creates the second database used by the pytest suite, so that running the
#  tests never touches the imported market data.
# =============================================================================
set -e

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" \
     -c "CREATE DATABASE \"${TEST_DB:-crypto_test}\""
