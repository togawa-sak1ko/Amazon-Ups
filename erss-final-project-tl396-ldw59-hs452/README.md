# Mini-UPS Starter

This repository is an initial UPS-side implementation for the ERSS final project. It is built around Django for the web tier, Postgres for shared state, and a separate daemon layer for world simulator traffic.

## What is here

- A Django app for shipment tracking, account-based package views, and pre-delivery redirects.
- Postgres-ready models for shipments, trucks, world sessions, events, and queued world commands.
- JSON endpoints aligned to the current Amazon/UPS interoperability contract.
- A live-capable world daemon with protobuf framing helpers and reconnect handling for `world_ups.proto`.
- Docker and developer docs so the repo can grow into the final deliverable shape.

## UPS scope mapped from the spec

- Bare minimum:
  - Show shipments and status in a web UI.
  - Create a package/tracking record.
  - Queue truck pickup and delivery work.
- Actually useful:
  - Tracking-number lookup.
  - User login and package ownership.
  - Redirect before the package goes out for delivery.
  - Package detail view including shipment items.

## Quick start

1. Copy `.env.example` to `.env` and adjust values.
2. Install dependencies: `pip install -r requirements.txt`
3. Generate protobuf bindings (if needed): `make proto`
4. Run migrations: `python3 manage.py migrate`
5. Seed a world session + trucks: `python3 manage.py seed_world_session --trucks 3`
6. Start the server: `python3 manage.py runserver`
7. Run daemon:
   - Live world mode: `python3 manage.py run_world_daemon`
   - Dry-run: `UPS_WORLD_DAEMON_DRY_RUN=1 python3 manage.py run_world_daemon`

For Docker:

1. `docker compose up --build`
2. Initialize trucks: `docker compose exec web python manage.py seed_world_session --trucks 3`
3. Open `http://127.0.0.1:8081`

## Amazon/UPS protocol surface

The current UPS implementation now exposes the protocol endpoints described in the team spec:

- `POST /pickup`
- `POST /package-loaded`
- `POST /redirect`

It also contains callback hooks for UPS-to-Amazon notifications:

- `POST /truck-arrived`
- `POST /package-delivered`

## Important project notes

- The daemon now defaults to live world mode. Set `UPS_WORLD_DAEMON_DRY_RUN=1` only when you want to inspect the queue without dispatching.
- Set `DATABASE_BIND_PORT` if host port `5432` is already in use on your machine or VM.
- `proto/world_ups.proto` and `proto/world_amazon.proto` are included locally so you can generate bindings inside the repo later.
- Suggested next steps are in [docs/architecture.md](docs/architecture.md) and [docs/protocol-starter.md](docs/protocol-starter.md).
