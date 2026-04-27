#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORLD_DIR="$ROOT/world_simulator_exec/docker_deploy"
UPS_DIR="$ROOT/erss-final-project-tl396-ldw59-hs452"
AMAZON_DIR="$ROOT/erss-project-zx158-zq65"

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
else
  COMPOSE_CMD=(docker-compose)
fi

compose() {
  "${COMPOSE_CMD[@]}" "$@"
}

USE_VM_WORLD="${USE_VM_WORLD:-0}"
VM_WORLD_HOST="${VM_WORLD_HOST:-}"
LOCAL_WORLD_HOST="${LOCAL_WORLD_HOST:-host.docker.internal}"
UPS_WORLD_PORT="${UPS_WORLD_PORT:-12345}"
AMAZON_WORLD_PORT="${AMAZON_WORLD_PORT:-23456}"
AMAZON_HTTP_PORT="${AMAZON_HTTP_PORT:-8080}"
UPS_HTTP_PORT="${UPS_HTTP_PORT:-8081}"
UPS_ALLOWED_HOSTS="${UPS_ALLOWED_HOSTS:-127.0.0.1,localhost,host.docker.internal,vcm-51642.vm.duke.edu,67.159.74.167,67.159.75.250}"
UPS_CSRF_TRUSTED_ORIGINS="${UPS_CSRF_TRUSTED_ORIGINS:-http://127.0.0.1:8081,http://localhost:8081,http://vcm-51642.vm.duke.edu:8081,http://67.159.74.167:8081,http://67.159.75.250:8081,http://vcm-51642.vm.duke.edu:${UPS_HTTP_PORT},http://67.159.74.167:${UPS_HTTP_PORT},http://67.159.75.250:${UPS_HTTP_PORT}}"
AMAZON_UPS_HOST="${AMAZON_UPS_HOST:-host.docker.internal}"
AMAZON_UPS_PORT="${AMAZON_UPS_PORT:-$UPS_HTTP_PORT}"
UPS_AMAZON_HOST="${UPS_AMAZON_HOST:-host.docker.internal}"
UPS_AMAZON_PORT="${UPS_AMAZON_PORT:-$AMAZON_HTTP_PORT}"
SIM_SPEED="${SIM_SPEED:-100}"
UPS_POLL_INTERVAL="${UPS_POLL_INTERVAL:-1}"
UPS_TRUCK_COUNT="${UPS_TRUCK_COUNT:-12}"

write_amazon_env() {
  cat >"$AMAZON_DIR/.env" <<EOF
APP_ENV=dev
APP_HOST=0.0.0.0
APP_PORT=8080
HOST_APP_PORT=$AMAZON_HTTP_PORT
APP_NAME=team1c-amazon
SESSION_SECRET=dev-mini-amazon-session-secret
DATABASE_URL=postgresql+psycopg://postgres:postgres@db:5432/amazon
SYNC_DATABASE_URL=postgresql+psycopg://postgres:postgres@db:5432/amazon
AMAZON_HOST=web
AMAZON_PORT=8080
UPS_HOST=$AMAZON_UPS_HOST
UPS_PORT=$AMAZON_UPS_PORT
WORLD_HOST=$WORLD_HOST
WORLD_PORT=$AMAZON_WORLD_PORT
WORLD_ID=
WORLD_SIM_SPEED=$SIM_SPEED
WAREHOUSE_ID=1
WAREHOUSE_X=10
WAREHOUSE_Y=10
EOF
}

wait_for_healthz() {
  local url="$1"
  local attempts="${2:-60}"
  for _ in $(seq 1 "$attempts"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "ERROR: Timed out waiting for $url"
  echo "Last response:"
  curl -i "$url" || true
  return 1
}

read_amazon_world_id() {
  curl -fsS "http://127.0.0.1:${AMAZON_HTTP_PORT}/healthz" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
world_id = payload.get("world_id")
print("" if world_id is None else world_id)
'
}

if [[ "$USE_VM_WORLD" == "1" ]]; then
  if [[ -z "$VM_WORLD_HOST" ]]; then
    echo "ERROR: VM mode requires VM_WORLD_HOST."
    exit 1
  fi
  WORLD_HOST="$VM_WORLD_HOST"
  echo "==> Using VM world at $WORLD_HOST"
else
  WORLD_HOST="$LOCAL_WORLD_HOST"
  echo "==> Starting local world simulator"
  cd "$WORLD_DIR"
  compose down -v
  compose up -d --build
fi

echo "==> Starting UPS web stack"
cd "$UPS_DIR"
compose down -v
WORLD_HOST="$WORLD_HOST" \
WORLD_PORT="$UPS_WORLD_PORT" \
WORLD_DAEMON_DRY_RUN=0 \
AMAZON_HOST="$UPS_AMAZON_HOST" \
AMAZON_PORT="$UPS_AMAZON_PORT" \
UPS_HTTP_PORT="$UPS_HTTP_PORT" \
DJANGO_ALLOWED_HOSTS="$UPS_ALLOWED_HOSTS" \
DJANGO_CSRF_TRUSTED_ORIGINS="$UPS_CSRF_TRUSTED_ORIGINS" \
compose up -d --build db web

echo "==> Waiting for UPS web"
wait_for_healthz "http://127.0.0.1:${UPS_HTTP_PORT}/" 60

echo "==> Preparing Amazon env"
write_amazon_env

echo "==> Starting Amazon web + worker"
cd "$AMAZON_DIR"
compose down -v
compose up -d --build

echo "==> Waiting for Amazon healthz"
if ! wait_for_healthz "http://127.0.0.1:${AMAZON_HTTP_PORT}/healthz" 60; then
  echo
  echo "Amazon container status:"
  compose ps || true
  echo
  echo "Amazon web logs:"
  compose logs --tail 160 web || true
  echo
  echo "Amazon db logs:"
  compose logs --tail 80 db || true
  exit 1
fi

echo "==> Ensuring UPS demo login user exists"
cd "$UPS_DIR"
compose exec -T web python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
u, _ = User.objects.get_or_create(username='integration_user', defaults={'email': 'integration@example.com'})
u.set_password('HelloWorld1234')
u.save()
print('UPS login user ready:', u.username)
"

echo "==> Reading Amazon world id from /healthz"
WORLD_ID=""
for _ in $(seq 1 45); do
  WORLD_ID="$(read_amazon_world_id)"
  if [[ -n "$WORLD_ID" ]]; then
    break
  fi
  sleep 2
done

if [[ -z "$WORLD_ID" ]]; then
  echo "ERROR: Amazon did not publish a world_id in /healthz."
  echo
  echo "Amazon /healthz:"
  curl -i "http://127.0.0.1:${AMAZON_HTTP_PORT}/healthz" || true
  echo
  echo "Amazon container status:"
  cd "$AMAZON_DIR"
  compose ps || true
  echo
  echo "Amazon worker logs:"
  compose logs --tail 180 worker || true
  echo
  echo "Amazon web logs:"
  compose logs --tail 80 web || true
  if [[ "$USE_VM_WORLD" != "1" ]]; then
    echo
    echo "World simulator logs:"
    cd "$WORLD_DIR"
    compose logs --tail 120 server || true
  fi
  exit 1
fi

echo "Amazon world id: $WORLD_ID"

echo "==> Aligning UPS world session"
cd "$UPS_DIR"
WORLD_HOST="$WORLD_HOST" \
WORLD_PORT="$UPS_WORLD_PORT" \
WORLD_DAEMON_DRY_RUN=0 \
AMAZON_HOST="$UPS_AMAZON_HOST" \
AMAZON_PORT="$UPS_AMAZON_PORT" \
compose exec -T web python manage.py shell -c "
from ups.models import WorldSession, Truck
s, _ = WorldSession.objects.get_or_create(name='primary')
s.world_id = int('$WORLD_ID')
s.is_connected = False
s.host = '$WORLD_HOST'
s.port = int('$UPS_WORLD_PORT')
s.save(update_fields=['world_id', 'is_connected', 'host', 'port', 'updated_at'])
target_truck_count = int('$UPS_TRUCK_COUNT')
existing = set(Truck.objects.filter(world_session=s).values_list('truck_id', flat=True))
for truck_id in range(1, target_truck_count + 1):
    if truck_id not in existing:
        Truck.objects.create(world_session=s, truck_id=truck_id, current_x=0, current_y=0)
Truck.objects.filter(world_session=s, truck_id__gt=target_truck_count).delete()
print('UPS session ->', s.world_id, s.host, s.port)
print('UPS trucks ->', target_truck_count)
"

echo "==> Starting UPS daemon"
docker rm -f ups-daemon >/dev/null 2>&1 || true
WORLD_HOST="$WORLD_HOST" \
WORLD_PORT="$UPS_WORLD_PORT" \
WORLD_DAEMON_DRY_RUN=0 \
AMAZON_HOST="$UPS_AMAZON_HOST" \
AMAZON_PORT="$UPS_AMAZON_PORT" \
compose run -d --name ups-daemon daemon python manage.py run_world_daemon --poll-interval "$UPS_POLL_INTERVAL"

echo
echo "All stacks started."
echo "Amazon UI: http://127.0.0.1:${AMAZON_HTTP_PORT}"
echo "UPS UI:    http://127.0.0.1:${UPS_HTTP_PORT}"
echo
echo "Useful logs:"
echo "  cd \"$WORLD_DIR\"  && ${COMPOSE_CMD[*]} logs -f server"
echo "  cd \"$UPS_DIR\"    && ${COMPOSE_CMD[*]} logs -f web && docker logs -f ups-daemon"
echo "  cd \"$AMAZON_DIR\" && ${COMPOSE_CMD[*]} logs -f web && ${COMPOSE_CMD[*]} logs -f worker"
