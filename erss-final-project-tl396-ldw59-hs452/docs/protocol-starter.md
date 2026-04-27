# Amazon/UPS Protocol Summary

This file is a code-facing summary of the agreed Amazon/UPS protocol in
`/Users/nautilus/Desktop/Duke_Spring2026/ECE568/final_project/Amazon-UPS Protocol Spec.docx`.
It replaces the earlier starter contract that used `/api/shipments/...`.

## Transport

- Protocol: HTTP/JSON over a private bridge network between containers.
- Amazon listens on port `8080`.
- UPS listens on port `8081`.
- UPS configures Amazon via `AMAZON_HOST`.
- Amazon configures UPS via `UPS_HOST`.
- Network errors and HTTP 5xx responses should be retried with exponential backoff up to 3 times.

## UPS endpoints

### `POST /pickup`

Purpose: register a package with UPS and dispatch a truck to the warehouse.

Example body:

```json
{
  "world_id": 1001,
  "package_id": 77,
  "warehouse_id": 2,
  "dest_x": 14,
  "dest_y": 9,
  "ups_username": "alice"
}
```

Success response:

```json
{
  "truck_id": 4
}
```

### `POST /package-loaded`

Purpose: Amazon tells UPS that World confirmed the package is on the truck, so UPS can queue delivery.

Example body:

```json
{
  "package_id": 77,
  "truck_id": 4,
  "dest_x": 20,
  "dest_y": 6
}
```

### `POST /redirect`

Purpose: request a delivery address change by `package_id`.

Example body:

```json
{
  "package_id": 77,
  "dest_x": 20,
  "dest_y": 6
}
```

Success response:

```json
{
  "success": true,
  "message": "Delivery address updated."
}
```

If the package is already out for delivery, UPS returns:

```json
{
  "success": false,
  "message": "This shipment can no longer be redirected."
}
```

## UPS callbacks to Amazon

### `POST /truck-arrived`

Sent when the assigned UPS truck reaches the warehouse and is ready to load.

### `POST /package-delivered`

Sent when World confirms delivery completion.

## Required behavior

- Amazon-generated `package_id` is the cross-system package identifier.
- `ups_username` binds a package into a UPS user account when present.
- UPS must not queue delivery before receiving `/package-loaded`.
- Redirects must be rejected once the package is out for delivery.
- On request failure, UPS should return HTTP 4xx with `{ "error": "<message>" }`.

## Legacy compatibility

The older `/api/shipments/...` endpoints still exist in the repo for local tooling and UI support,
but they are no longer the primary IG contract.
