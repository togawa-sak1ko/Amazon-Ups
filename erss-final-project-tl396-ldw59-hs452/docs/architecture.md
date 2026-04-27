# UPS Architecture Notes

## High-level split

- Django web tier:
  - login and session management
  - shipment list/detail pages
  - tracking lookup
  - redirect workflow
  - JSON APIs for Amazon/UPS coordination
- Postgres:
  - source of truth for shipments, items, trucks, queued commands, and event history
- World daemon:
  - owns socket communication with the world simulator
  - converts queued `WorldCommand` rows into protobuf messages
  - consumes async world responses and reconciles shipment/truck state

## Current data model

- `WorldSession`: one row per world connection context.
- `Truck`: UPS-controlled trucks and their last known position/state.
- `Shipment`: package identity, ownership, routing, and lifecycle status.
- `ShipmentItem`: shipment contents for the package detail page.
- `ShipmentEvent`: audit trail used in the UI and debugging.
- `WorldCommand`: queued outbound world work plus future ack/retry state.

## Suggested next implementation steps

1. Finalize the IG protocol.
2. Generate Python protobuf bindings from `proto/world_ups.proto`.
3. Implement `WorldSocketClient.dispatch()` by translating queued commands into `UCommands`.
4. Add a response listener that updates shipments/trucks from `UResponses`.
5. Seed trucks and world connection flow in a bootstrap management command.
6. Add demo data and admin workflows for local testing.

## Why this structure fits the spec

- The spec explicitly allows Django plus a separate backend/daemon.
- The world replies asynchronously, so blocking web requests on world traffic would be fragile.
- Shared Postgres makes it easy for the UI and daemon to stay synchronized without custom in-process state.

