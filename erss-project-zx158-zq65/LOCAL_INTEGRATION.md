# Local Amazon/UPS Integration

This repo is the Amazon side. The UPS repo is expected to run as a separate stack.

## Amazon defaults for local integration

- Amazon HTTP: `http://localhost:8080`
- UPS HTTP from Amazon containers: `http://host.docker.internal:8081`
- World from Amazon containers: `host.docker.internal:23456`
- UPS connects to the same world simulator through its UPS port: `host.docker.internal:12345`
- Warehouse: id `1` at `(10, 10)`

These defaults live in `.env.example` and can be copied to `.env`.

## Start Amazon

```bash
cd /Users/felix/git/integration_workspace/amazon-team1c
cp .env.example .env
docker compose up --build
```

Health check:

```bash
curl -i http://localhost:8080/healthz
```

## Minimal checklist

1. World simulator is running with Amazon on port `23456` and UPS on port `12345`.
2. Amazon web is reachable at `http://localhost:8080/healthz`.
3. UPS web is reachable at `http://localhost:8081`.
4. UPS was started with `AMAZON_HOST=host.docker.internal`, `AMAZON_PORT=8080`, and `DJANGO_ALLOWED_HOSTS` including `host.docker.internal`.
5. UPS trucks were seeded with `python manage.py seed_world_session --trucks 3`.
6. UPS world daemon is running without `--dry-run`.
7. Create one Amazon order and watch for this order: `/pickup`, `/truck-arrived`, world load, `/package-loaded`, world delivery, `/package-delivered`.

## UPS runtime settings to coordinate

Do not edit the UPS repo from here, but run it with settings compatible with this Amazon stack:

```bash
AMAZON_HOST=host.docker.internal
AMAZON_PORT=8080
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,host.docker.internal
WORLD_HOST=host.docker.internal
WORLD_PORT=12345
WORLD_DAEMON_DRY_RUN=0
```

The UPS compose file hard-codes the daemon command with `--dry-run`, so for live world testing start UPS web/db, seed trucks, then run the daemon with an override command.

Example from `../ups-team1a`:

```bash
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,host.docker.internal \
AMAZON_HOST=host.docker.internal \
AMAZON_PORT=8080 \
WORLD_HOST=host.docker.internal \
WORLD_PORT=12345 \
docker compose up --build web db
```

In another shell:

```bash
cd /Users/felix/git/integration_workspace/ups-team1a
docker compose exec web python manage.py seed_world_session --trucks 3
WORLD_DAEMON_DRY_RUN=0 \
WORLD_HOST=host.docker.internal \
WORLD_PORT=12345 \
AMAZON_HOST=host.docker.internal \
AMAZON_PORT=8080 \
docker compose run --rm daemon python manage.py run_world_daemon --poll-interval 5
```

## Manual callback checks

These prove UPS can reach Amazon's inbound protocol endpoints. Use a package id that exists in Amazon for 200 responses.

```bash
curl -i -X POST http://localhost:8080/truck-arrived \
  -H 'Content-Type: application/json' \
  -d '{"truck_id":1,"warehouse_id":1,"package_id":1}'
```

```bash
curl -i -X POST http://localhost:8080/package-delivered \
  -H 'Content-Type: application/json' \
  -d '{"package_id":1}'
```

## Expected Amazon outbound payloads

Amazon worker sends these to UPS. These curl commands are useful for manually testing the UPS protocol endpoints.

```bash
curl -i -X POST http://localhost:8081/pickup \
  -H 'Content-Type: application/json' \
  -d '{"package_id":1,"warehouse_id":1,"dest_x":20,"dest_y":30,"ups_username":"alice"}'
```

```bash
curl -i -X POST http://localhost:8081/package-loaded \
  -H 'Content-Type: application/json' \
  -d '{"package_id":1,"truck_id":1,"dest_x":20,"dest_y":30}'
```

```bash
curl -i -X POST http://localhost:8081/redirect \
  -H 'Content-Type: application/json' \
  -d '{"package_id":1,"dest_x":25,"dest_y":35}'
```
