# FastAPI backend for the Crypto Market Data Explorer.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first so Docker can cache this layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code (tests included, so `pytest` can run inside the container).
COPY . .

EXPOSE 8000

# start.sh waits for PostgreSQL, applies the schema, imports the CSV files
# and then launches the API server. Every step is idempotent.
CMD ["./start.sh"]
