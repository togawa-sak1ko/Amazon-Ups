#!/bin/sh
set -e

sh ./scripts/gen-proto.sh
python -m app.bootstrap
exec python -m app.workers.world_worker
