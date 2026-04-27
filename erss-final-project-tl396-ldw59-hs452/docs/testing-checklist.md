# Mini-UPS Testing Checklist

Use this checklist to validate Mini-UPS before Mini-Amazon integration is ready.

## 1. Setup

```bash
cd /Users/nautilus/Desktop/Duke_Spring2026/ECE568/final_project/erss-final-project-tl396-ldw59-hs452
pip install -r requirements.txt
python3 manage.py migrate
python3 manage.py seed_world_session --trucks 3
python3 manage.py seed_mock_portal_data
python3 manage.py runserver
```

Open:

- `http://127.0.0.1:8000`

## 2. Demo Accounts

- `demo_customer` / `demo-pass-123`
- `demo_receiver` / `demo-pass-123`

## 3. Seeded Tracking Numbers

- `610001`
- `UPS-MOCK-LOAD`
- `UPS-MOCK-ROUTE`
- `UPS-MOCK-DONE`

## 4. Manual Portal Tests

1. Homepage
   - Visit `/`
   - Confirm tracking form, login link, and signup link render

2. Signup
   - Visit `/accounts/signup/`
   - Create a new account such as `manualtest1`
   - Confirm redirect to `/dashboard/`

3. Login
   - Log out
   - Sign in as `demo_customer`

4. Valid tracking by package ID
   - Enter `610001` on `/`
   - Confirm redirect to the tracking detail page

5. Valid tracking by tracking number
   - Enter `UPS-MOCK-LOAD` on `/`
   - Confirm redirect to the tracking detail page

6. Invalid tracking
   - Enter `BAD-TRACKING` on `/`
   - Confirm the app stays on `/`
   - Confirm a popup alert says tracking number is invalid or not found

7. Dashboard and shipment list
   - Visit `/dashboard/` and `/shipments/`
   - Confirm `demo_customer` can see `610001`, `UPS-MOCK-LOAD`, and `UPS-MOCK-DONE`

8. Redirect success
   - Open `/shipments/610001/`
   - Submit a new destination
   - Confirm success message appears

9. Redirect blocked
   - Log in as `demo_receiver`
   - Open `/shipments/UPS-MOCK-ROUTE/`
   - Confirm redirect is not allowed because the shipment is already out for delivery

10. Support center
   - Visit `/support/`
   - Submit a ticket for `610001`
   - Confirm it appears in recent tickets

11. Quote workflow
   - Visit `/quote/`
   - Submit an estimate
   - Confirm it appears in quote history

12. Alerts, search, and locations
   - Visit `/alerts/`
   - Confirm shipment and support activity appears
   - Search for `610001`, `demo_customer`, `support`, and `Durham`
   - Visit `/locations/?query=Durham`

13. Shipping overview
   - Visit `/shipping/`
   - Confirm shipments, support, and quotes are populated

## 5. API Tests

Check shipment status:

```bash
curl http://127.0.0.1:8000/api/shipments/610001/status/
```

Create a mock pickup:

```bash
curl -X POST http://127.0.0.1:8000/pickup \
  -H 'Content-Type: application/json' \
  -d '{"world_id":9901,"package_id":710001,"warehouse_id":4,"dest_x":7,"dest_y":9,"ups_username":"demo_customer"}'
```

Redirect the same package:

```bash
curl -X POST http://127.0.0.1:8000/redirect \
  -H 'Content-Type: application/json' \
  -d '{"package_id":710001,"dest_x":10,"dest_y":12}'
```

Mark it loaded:

```bash
curl -X POST http://127.0.0.1:8000/package-loaded \
  -H 'Content-Type: application/json' \
  -d '{"package_id":710001,"truck_id":21,"dest_x":10,"dest_y":12}'
```

Then:

- track `710001` from the homepage
- try `/redirect` again for `710001`
- confirm the response returns `success: false` once the package is out for delivery

## 6. Automated Tests

Run the portal-focused tests:

```bash
python3 manage.py test ups.tests.PortalWorkflowTests ups.tests.SeedMockPortalDataCommandTests ups.tests.ShipmentApiTests
```

## 7. Supporting Docs

- Seed output and proof: `docs/mock-data-validation.md`
- Protocol notes: `docs/protocol-starter.md`
- Architecture notes: `docs/architecture.md`
