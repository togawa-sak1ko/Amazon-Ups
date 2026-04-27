#!/bin/sh
set -e

sh ./scripts/gen-proto.sh
python -m app.bootstrap
exec uvicorn app.main:app --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8080}"
