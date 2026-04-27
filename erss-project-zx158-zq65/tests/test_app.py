from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.ups_api import RedirectResponse
from app.services.order_service import create_order, mark_pickup_requested
from app.schemas.order import OrderCreate
from app.services.runtime_state_service import set_runtime_int


engine = create_engine(
    "sqlite://",
    future=True,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base.metadata.create_all(engine)


def reset_db() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


client = TestClient(app)


def test_healthcheck() -> None:
    reset_db()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "world_id": None}


def test_healthcheck_reports_persisted_world_id() -> None:
    reset_db()
    db = TestingSessionLocal()
    try:
        set_runtime_int(db, "world_id", 999)
        db.commit()
    finally:
        db.close()

    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "world_id": 999}


def test_ups_callback_missing_package_uses_protocol_error_body() -> None:
    reset_db()

    response = client.post("/truck-arrived", json={"truck_id": 1, "warehouse_id": 1, "package_id": 999})
    assert response.status_code == 404
    assert response.json() == {"error": "Package not found"}


def test_ups_callback_validation_error_uses_protocol_error_body() -> None:
    reset_db()

    response = client.post("/truck-arrived", json={"truck_id": 1, "warehouse_id": 1})
    assert response.status_code == 422
    assert response.json() == {"error": "Invalid request body"}


def test_redirect_order_updates_destination_before_delivery(monkeypatch) -> None:
    reset_db()

    class StubUPSClient:
        def redirect_package(self, payload):  # pragma: no cover - signature shim
            raise AssertionError("UPS redirect should not be called before pickup is requested")

    monkeypatch.setattr("app.api.orders.UPSClient", StubUPSClient)

    db = TestingSessionLocal()
    try:
        order = create_order(
            db,
            OrderCreate(
                product_name="Widget",
                quantity=1,
                dest_x=3,
                dest_y=4,
            ),
        )
    finally:
        db.close()

    response = client.post(
        f"/orders/{order.order_id}/redirect",
        data={"dest_x": 30, "dest_y": 40},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Destination updated." in response.text
    assert "(30, 40)" in response.text


def test_redirect_order_calls_ups_after_pickup(monkeypatch) -> None:
    reset_db()
    calls = []

    class StubUPSClient:
        def redirect_package(self, payload):
            calls.append(payload.model_dump())
            return RedirectResponse(success=True, message="updated")

    monkeypatch.setattr("app.api.orders.UPSClient", StubUPSClient)

    db = TestingSessionLocal()
    try:
        order = create_order(
            db,
            OrderCreate(
                product_name="Widget",
                quantity=1,
                dest_x=5,
                dest_y=6,
            ),
        )
        mark_pickup_requested(db, order.package_id, truck_id=42)
    finally:
        db.close()

    response = client.post(
        f"/orders/{order.order_id}/redirect",
        data={"dest_x": 50, "dest_y": 60},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert calls == [{"package_id": order.package_id, "dest_x": 50, "dest_y": 60}]
    assert "(50, 60)" in response.text
