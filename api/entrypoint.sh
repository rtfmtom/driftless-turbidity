#!/usr/bin/env bash
set -euo pipefail

wait_for_db() {
    local max_attempts=60
    local attempt=0
    echo "Waiting for database at ${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}..."
    until python - <<'PY' >/dev/null 2>&1
import os
import psycopg
conn = psycopg.connect(
    host=os.environ.get("POSTGRES_HOST", "db"),
    port=int(os.environ.get("POSTGRES_PORT", "5432")),
    user=os.environ.get("POSTGRES_USER", "driftless"),
    password=os.environ.get("POSTGRES_PASSWORD", "driftless"),
    dbname=os.environ.get("POSTGRES_DB", "driftless"),
    connect_timeout=3,
)
conn.close()
PY
    do
        attempt=$((attempt+1))
        if [ "$attempt" -ge "$max_attempts" ]; then
            echo "Database did not become ready in time." >&2
            exit 1
        fi
        sleep 1
    done
    echo "Database is up."
}

run_migrations() {
    echo "Running alembic upgrade head..."
    alembic upgrade head
}

cmd="${1:-api}"

case "$cmd" in
    migrate)
        wait_for_db
        run_migrations
        ;;
    api)
        wait_for_db
        run_migrations
        if [ "${DRIFTLESS_DEV:-0}" = "1" ]; then
            exec uvicorn driftless.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir /app/src
        else
            exec uvicorn driftless.main:app --host 0.0.0.0 --port 8000
        fi
        ;;
    ingest-once)
        wait_for_db
        shift || true
        exec python -m driftless.ingest.usgs "$@"
        ;;
    *)
        exec "$@"
        ;;
esac
