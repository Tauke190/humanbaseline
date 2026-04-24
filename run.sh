#!/usr/bin/env bash
# Launch the human baseline annotation server.
#
# Usage:
#   bash run.sh              # default port 5050
#   PORT=8080 bash run.sh    # custom port
#
# Sessions are saved to:   human_baseline/data/sessions/<uuid>.json
# Class exposure counts:   human_baseline/data/class_counts.json

set -e
cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}
PORT=${PORT:-5050}

WORKERS=${WORKERS:-4}
echo "Starting gunicorn (${WORKERS} workers) at http://0.0.0.0:${PORT}  (Ctrl-C to stop)"
exec gunicorn \
  --workers "$WORKERS" \
  --bind "0.0.0.0:${PORT}" \
  --timeout 120 \
  --worker-class gthread \
  --threads 4 \
  app:app
