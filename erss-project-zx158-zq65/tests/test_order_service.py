from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models.order import OrderStatus
from app.models.warehouse import InventoryItem
from app.services.order_service import (
    create_order,
    get_order,
    get_shipments_needing_delivery_notice,
    get_shipments_needing_inventory,
    get_shipments_needing_load,
    get_shipments_needing_pack,
    get_shipments_needing_pickup,
    mark_delivery_notified,
    mark_delivered,
    mark_failure,
    mark_inventory_arrived,
    mark_inventory_requested,
    mark_load_requested,
    mark_loaded,
    mark_pack_requested,
    mark_packed,
    mark_pickup_requested,
    mark_truck_arrived,
    update_order_destination,
)
from app.schemas.order import OrderCreate
from app.services.runtime_state_service import get_runtime_int, set_runtime_int


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()


def test_order_progression_updates_human_status() -> None:
    db = make_session()
    order = create_order(
        db,
        OrderCreate(
            product_name="Widget",
            quantity=2,
            dest_x=7,
            dest_y=9,
            ups_username="alice",
        ),
    )

    assert order.status == OrderStatus.CREATED.value

    assert mark_pickup_requested(db, order.package_id, truck_id=42)
    assert get_order(db, order.order_id).status == OrderStatus.PICKUP_REQUESTED.value

    assert mark_inventory_requested(db, order.package_id)
    assert mark_inventory_arrived(db, order.package_id)
    assert mark_pack_requested(db, order.package_id)
    assert get_order(db, order.order_id).status == OrderStatus.PACKING_REQUESTED.value

    assert mark_packed(db, order.package_id)
    assert get_order(db, order.order_id).status == OrderStatus.PACKED.value

    assert mark_truck_arrived(db, order.package_id, truck_id=42, warehouse_id=1)
    assert get_order(db, order.order_id).status == OrderStatus.TRUCK_ARRIVED.value

    assert mark_load_requested(db, order.package_id)
    assert get_order(db, order.order_id).status == OrderStatus.LOADING_REQUESTED.value

    assert mark_loaded(db, order.package_id)
    assert mark_delivery_notified(db, order.package_id)
    assert get_order(db, order.order_id).status == OrderStatus.OUT_FOR_DELIVERY.value

    assert mark_delivered(db, order.package_id)
    view = get_order(db, order.order_id)
    assert view.status == OrderStatus.DELIVERED.value
    assert view.truck_id == 42
    assert view.last_error is None


def test_failed_shipment_is_removed_from_worker_queues() -> None:
    db = make_session()
    order = create_order(
        db,
        OrderCreate(
            product_name="Widget",
            quantity=1,
            dest_x=2,
            dest_y=3,
        ),
    )

    assert mark_failure(db, order.package_id, "pickup failed")

    assert get_shipments_needing_pickup(db) == []
    assert get_shipments_needing_inventory(db) == []
    assert get_shipments_needing_pack(db) == []
    assert get_shipments_needing_load(db) == []
    assert get_shipments_needing_delivery_notice(db) == []


def test_inventory_is_updated_by_world_events() -> None:
    db = make_session()
    order = create_order(
        db,
        OrderCreate(
            product_name="Widget",
            quantity=3,
            dest_x=7,
            dest_y=9,
        ),
    )

    assert mark_inventory_arrived(db, order.package_id)
    item = db.query(InventoryItem).filter_by(warehouse_id=1, product_name="Widget").one()
    assert item.quantity == 3

    assert mark_packed(db, order.package_id)
    db.refresh(item)
    assert item.quantity == 0


def test_redirect_updates_destination() -> None:
    db = make_session()
    order = create_order(
        db,
        OrderCreate(
            product_name="Widget",
            quantity=1,
            dest_x=1,
            dest_y=1,
        ),
    )

    updated = update_order_destination(db, order.order_id, dest_x=11, dest_y=12)
    assert updated is not None
    assert updated.dest_x == 11
    assert updated.dest_y == 12


def test_package_ids_are_allocated_from_counter() -> None:
    db = make_session()

    first = create_order(
        db,
        OrderCreate(product_name="Widget", quantity=1, dest_x=1, dest_y=1),
    )
    second = create_order(
        db,
        OrderCreate(product_name="Widget", quantity=1, dest_x=2, dest_y=2),
    )

    assert first.package_id == 1
    assert second.package_id == 2


def test_runtime_world_id_is_persisted() -> None:
    db = make_session()

    assert get_runtime_int(db, "world_id") is None
    set_runtime_int(db, "world_id", 2345)
    db.commit()

    assert get_runtime_int(db, "world_id") == 2345
