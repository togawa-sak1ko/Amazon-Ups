# Team 1c Amazon

Amazon-side implementation for the ERSS final project. The app now includes a working FastAPI UI, persisted order state, UPS HTTP integration, and a worker that coordinates Amazon world commands with UPS callbacks.

## Stack

- FastAPI
- SQLAlchemy
- PostgreSQL
- Jinja2 templates
- Docker Compose

## Services

- `web`: HTTP server on port `8080`
- `worker`: background process for world/UPS orchestration
- `db`: PostgreSQL

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Then open `http://localhost:8080`.

For running this Amazon stack against the separate UPS repo on one machine, see
[`LOCAL_INTEGRATION.md`](LOCAL_INTEGRATION.md).

## Implemented flow

- Searchable catalog and order creation UI
- Order, shipment, and warehouse persistence
- Delivery address redirect flow from Amazon
- UPS endpoints:
  `POST /pickup` from Amazon worker
  `POST /truck-arrived` callback from UPS
  `POST /package-loaded` from Amazon worker
  `POST /package-delivered` callback from UPS
  `POST /redirect` from Amazon when a destination changes after pickup is scheduled
- World simulator integration over protobuf with:
  `AConnect`
  `APurchaseMore`
  `APack`
  `APutOnTruck`
  `seqnum`/`ack` handling
- Background worker that advances shipments through:
  `created -> pickup_requested -> packing_requested -> packed -> truck_arrived -> loading_requested -> loaded -> out_for_delivery -> delivered`

## Notes

- `scripts/gen-proto.sh` runs during image build and again at container startup. This avoids stale generated protobuf code when the repo is bind-mounted through Docker Compose.
- The worker buys per-order inventory in the world simulator, waits for the `arrived` notification, then packs, loads, and notifies UPS only after the world reports `loaded`.
- The project expects the UPS service to follow the protocol in the team document:
  `/pickup`
  `/truck-arrived`
  `/package-loaded`
  `/package-delivered`

## Verification

- `python -m compileall app tests`
- `.venv/bin/pytest`: `12 passed`
