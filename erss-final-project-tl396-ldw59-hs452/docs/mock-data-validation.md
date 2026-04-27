# Mock Data Validation

This project can be exercised before Mini-Amazon integration is ready by seeding deterministic portal data.

## Seed Command

Run:

```bash
python3 manage.py migrate --noinput
python3 manage.py seed_mock_portal_data
```

The command creates:

- demo users
  - `demo_customer` / `demo-pass-123`
  - `demo_receiver` / `demo-pass-123`
- seeded shipments in multiple statuses
  - `610001`
  - `UPS-MOCK-LOAD`
  - `UPS-MOCK-ROUTE`
  - `UPS-MOCK-DONE`
- seeded support tickets
- seeded saved quotes

## Verification Output

Seed command output captured on `vcm-51642.vm.duke.edu`:

```text
Operations to perform:
  Apply all migrations: admin, auth, contenttypes, sessions, ups
Running migrations:
  No migrations to apply.
Mock Mini-UPS portal data is ready.
Session: mock-portal (world_id=9901)
Users:
  - demo_customer / demo-pass-123 / demo_customer@example.com
  - demo_receiver / demo-pass-123 / demo_receiver@example.com
Tracking numbers:
  - 610001 (Truck en route to warehouse) owner=demo_customer
  - UPS-MOCK-LOAD (Loading) owner=demo_customer
  - UPS-MOCK-ROUTE (Out for delivery) owner=demo_receiver
  - UPS-MOCK-DONE (Delivered) owner=demo_customer
Support tickets: 3
Saved quotes: 2
```

Seeded record counts confirmed on the VM:

```text
users 2
shipments 4
tickets 3
quotes 2
```

Portal-focused regression tests captured on the VM:

```text
Found 14 test(s).
Creating test database for alias 'default'...
System check identified no issues (0 silenced).
..............
----------------------------------------------------------------------
Ran 14 tests in 1.529s

OK
Destroying test database for alias 'default'...
```

## Notes

- The new portal-focused tests cover signup, valid tracking lookup, invalid tracking alerts, support flow, portal search, and the mock-data seed command.
- The full suite on the VM still has one unrelated environment failure in the protobuf binding test because `google.protobuf` is not installed in that VM Python environment, even though `protobuf` is already listed in `requirements.txt`.
