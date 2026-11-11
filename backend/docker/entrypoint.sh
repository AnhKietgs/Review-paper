#!/bin/sh
set -eu
alembic upgrade head
if [ "${SEED_SAMPLE_DATA:-1}" = "1" ] && [ -f /app/demo_data/library.json ]; then
    python -m app.demo.seed --if-empty
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000

