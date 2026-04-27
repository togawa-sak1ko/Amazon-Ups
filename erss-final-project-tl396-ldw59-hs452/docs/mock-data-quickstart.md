# Mock Data Quickstart For Partners

Use this if you just want to boot Mini-UPS with stub data and click through the main flows.

## 1. Start From `tianji`

```bash
git checkout tianji
git pull origin tianji
```

## 2. Install And Initialize

```bash
pip install -r requirements.txt
python3 manage.py migrate
python3 manage.py seed_world_session --trucks 3
python3 manage.py seed_mock_portal_data
python3 manage.py runserver
```

Open:

- `http://127.0.0.1:8000`

## 3. Demo Accounts

- `demo_customer` / `demo-pass-123`
- `demo_receiver` / `demo-pass-123`

## 4. Demo Tracking Numbers

- `610001`
- `UPS-MOCK-LOAD`
- `UPS-MOCK-ROUTE`
- `UPS-MOCK-DONE`

## 5. Fastest Things To Test

1. Signup
   - visit `/accounts/signup/`
   - create a test account

2. Login
   - sign in as `demo_customer`

3. Tracking
   - enter `610001`
   - enter `UPS-MOCK-LOAD`
   - enter `BAD-TRACKING` and confirm the popup alert appears

4. Dashboard and shipments
   - open `/dashboard/`
   - open `/shipments/`

5. Redirect flow
   - open `/shipments/610001/` and submit a redirect
   - open `/shipments/UPS-MOCK-ROUTE/` and confirm redirect is blocked

6. Support and quote
   - open `/support/` and submit a ticket
   - open `/quote/` and save an estimate

7. Alerts and locations
   - open `/alerts/`
   - open `/locations/?query=Durham`

## 6. Reset The Stub Data

You can rerun the seed command at any time:

```bash
python3 manage.py seed_mock_portal_data
```

It will refresh the demo users, shipments, tickets, and quotes.

## 7. More Detail

- full testing flow: `docs/testing-checklist.md`
- seed proof/output: `docs/mock-data-validation.md`
