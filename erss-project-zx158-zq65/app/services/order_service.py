from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models.order import Order, OrderStatus
from app.models.shipment import Shipment
from app.models.warehouse import InventoryItem
from app.schemas.order import OrderCreate, OrderView
from app.services.package_id_service import next_package_id


def _shipment_query() -> object:
    return select(Shipment).options(selectinload(Shipment.order))


def _apply_status(order: Order, shipment: Shipment) -> None:
    if shipment.delivered:
        order.status = OrderStatus.DELIVERED.value
    elif shipment.delivery_notified:
        order.status = OrderStatus.OUT_FOR_DELIVERY.value
    elif shipment.loaded:
        order.status = OrderStatus.LOADED.value
    elif shipment.load_requested:
        order.status = OrderStatus.LOADING_REQUESTED.value
    elif shipment.truck_arrived:
        order.status = OrderStatus.TRUCK_ARRIVED.value
    elif shipment.packed:
        order.status = OrderStatus.PACKED.value
    elif shipment.pack_requested or shipment.inventory_requested:
        order.status = OrderStatus.PACKING_REQUESTED.value
    elif shipment.pickup_requested:
        order.status = OrderStatus.PICKUP_REQUESTED.value
    elif shipment.last_error:
        order.status = OrderStatus.FAILED.value
    else:
        order.status = OrderStatus.CREATED.value
    shipment.status = order.status


def _to_view(order: Order, shipment: Shipment) -> OrderView:
    return OrderView(
        order_id=order.id,
        package_id=shipment.package_id,
        product_name=order.product_name,
        quantity=order.quantity,
        dest_x=order.dest_x,
        dest_y=order.dest_y,
        status=order.status,
        warehouse_id=shipment.warehouse_id,
        truck_id=shipment.truck_id,
        ups_username=order.ups_username,
        last_error=shipment.last_error,
    )


def _get_shipment(db: Session, package_id: int) -> Optional[Shipment]:
    stmt = _shipment_query().where(Shipment.package_id == package_id)
    return db.scalar(stmt)


def _get_order(db: Session, order_id: int) -> Optional[Order]:
    stmt = select(Order).options(selectinload(Order.shipment)).where(Order.id == order_id)
    return db.scalar(stmt)


def _get_inventory_item(db: Session, warehouse_id: int, product_name: str) -> Optional[InventoryItem]:
    stmt = select(InventoryItem).where(
        InventoryItem.warehouse_id == warehouse_id,
        InventoryItem.product_name == product_name,
    )
    return db.scalar(stmt)


def _ensure_inventory_item(db: Session, warehouse_id: int, product_name: str) -> InventoryItem:
    item = _get_inventory_item(db, warehouse_id, product_name)
    if item is not None:
        return item
    item = InventoryItem(
        warehouse_id=warehouse_id,
        product_name=product_name,
        quantity=0,
    )
    db.add(item)
    db.flush()
    return item


def create_order(db: Session, payload: OrderCreate) -> OrderView:
    settings = get_settings()
    package_id = next_package_id(db)

    order = Order(
        product_name=payload.product_name,
        quantity=payload.quantity,
        dest_x=payload.dest_x,
        dest_y=payload.dest_y,
        ups_username=payload.ups_username,
        status=OrderStatus.CREATED.value,
    )
    db.add(order)
    db.flush()

    shipment = Shipment(
        order_id=order.id,
        package_id=package_id,
        warehouse_id=settings.warehouse_id,
        world_id=settings.world_id,
        truck_id=None,
        status=OrderStatus.CREATED.value,
    )
    _apply_status(order, shipment)
    db.add(shipment)
    db.commit()
    db.refresh(order)
    db.refresh(shipment)

    return _to_view(order, shipment)


def get_order(db: Session, order_id: int) -> Optional[OrderView]:
    order = _get_order(db, order_id)
    if order is None or order.shipment is None:
        return None
    return _to_view(order, order.shipment)


def get_order_by_package_id(db: Session, package_id: int) -> Optional[OrderView]:
    shipment = _get_shipment(db, package_id)
    if shipment is None:
        return None
    return _to_view(shipment.order, shipment)


def list_recent_orders(db: Session, limit: int = 5) -> list[OrderView]:
    stmt = (
        select(Order)
        .options(selectinload(Order.shipment))
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    orders = db.scalars(stmt)
    return [_to_view(order, order.shipment) for order in orders if order.shipment is not None]


def count_orders_by_status(db: Session) -> dict[str, int]:
    rows = db.execute(select(Order.status, func.count(Order.id)).group_by(Order.status)).all()
    return {status: count for status, count in rows}


def get_shipments_needing_pickup(db: Session) -> Sequence[Shipment]:
    stmt = _shipment_query().where(
        Shipment.pickup_requested.is_(False),
        Shipment.delivered.is_(False),
        Shipment.last_error.is_(None),
    )
    return list(db.scalars(stmt))


def get_shipments_needing_inventory(db: Session) -> Sequence[Shipment]:
    stmt = _shipment_query().where(
        Shipment.inventory_arrived.is_(False),
        Shipment.delivered.is_(False),
        Shipment.last_error.is_(None),
    )
    return list(db.scalars(stmt))


def get_shipments_needing_pack(db: Session) -> Sequence[Shipment]:
    stmt = _shipment_query().where(
        Shipment.inventory_arrived.is_(True),
        Shipment.packed.is_(False),
        Shipment.delivered.is_(False),
        Shipment.last_error.is_(None),
    )
    return list(db.scalars(stmt))


def get_shipments_needing_load(db: Session) -> Sequence[Shipment]:
    stmt = _shipment_query().where(
        Shipment.packed.is_(True),
        Shipment.truck_arrived.is_(True),
        Shipment.loaded.is_(False),
        Shipment.delivered.is_(False),
        Shipment.last_error.is_(None),
    )
    return list(db.scalars(stmt))


def get_shipments_needing_delivery_notice(db: Session) -> Sequence[Shipment]:
    stmt = _shipment_query().where(
        Shipment.loaded.is_(True),
        Shipment.delivery_notified.is_(False),
        Shipment.delivered.is_(False),
        Shipment.last_error.is_(None),
    )
    return list(db.scalars(stmt))


def mark_pickup_requested(db: Session, package_id: int, truck_id: int) -> bool:
    shipment = _get_shipment(db, package_id)
    if shipment is None:
        return False
    shipment.truck_id = truck_id
    shipment.pickup_requested = True
    shipment.last_error = None
    _apply_status(shipment.order, shipment)
    db.commit()
    return True


def mark_inventory_requested(db: Session, package_id: int) -> bool:
    shipment = _get_shipment(db, package_id)
    if shipment is None:
        return False
    shipment.inventory_requested = True
    shipment.last_error = None
    _apply_status(shipment.order, shipment)
    db.commit()
    return True


def mark_inventory_arrived(db: Session, package_id: int) -> bool:
    shipment = _get_shipment(db, package_id)
    if shipment is None:
        return False
    item = _ensure_inventory_item(db, shipment.warehouse_id, shipment.order.product_name)
    item.quantity += shipment.order.quantity
    shipment.inventory_arrived = True
    shipment.last_error = None
    _apply_status(shipment.order, shipment)
    db.commit()
    return True


def mark_pack_requested(db: Session, package_id: int) -> bool:
    shipment = _get_shipment(db, package_id)
    if shipment is None:
        return False
    shipment.pack_requested = True
    shipment.last_error = None
    _apply_status(shipment.order, shipment)
    db.commit()
    return True


def mark_packed(db: Session, package_id: int) -> bool:
    shipment = _get_shipment(db, package_id)
    if shipment is None:
        return False
    item = _ensure_inventory_item(db, shipment.warehouse_id, shipment.order.product_name)
    item.quantity = max(0, item.quantity - shipment.order.quantity)
    shipment.packed = True
    shipment.last_error = None
    _apply_status(shipment.order, shipment)
    db.commit()
    return True


def mark_truck_arrived(db: Session, package_id: int, truck_id: int, warehouse_id: int) -> bool:
    shipment = _get_shipment(db, package_id)
    if shipment is None or shipment.warehouse_id != warehouse_id:
        return False
    shipment.truck_id = truck_id
    shipment.truck_arrived = True
    shipment.last_error = None
    _apply_status(shipment.order, shipment)
    db.commit()
    return True


def mark_load_requested(db: Session, package_id: int) -> bool:
    shipment = _get_shipment(db, package_id)
    if shipment is None:
        return False
    shipment.load_requested = True
    shipment.last_error = None
    _apply_status(shipment.order, shipment)
    db.commit()
    return True


def mark_loaded(db: Session, package_id: int) -> bool:
    shipment = _get_shipment(db, package_id)
    if shipment is None:
        return False
    shipment.loaded = True
    shipment.last_error = None
    _apply_status(shipment.order, shipment)
    db.commit()
    return True


def mark_delivery_notified(db: Session, package_id: int) -> bool:
    shipment = _get_shipment(db, package_id)
    if shipment is None:
        return False
    shipment.delivery_notified = True
    shipment.last_error = None
    _apply_status(shipment.order, shipment)
    db.commit()
    return True


def mark_failure(db: Session, package_id: int, message: str) -> bool:
    shipment = _get_shipment(db, package_id)
    if shipment is None:
        return False
    shipment.last_error = message
    shipment.status = OrderStatus.FAILED.value
    shipment.order.status = OrderStatus.FAILED.value
    db.commit()
    return True


def mark_delivered(db: Session, package_id: int) -> bool:
    shipment = _get_shipment(db, package_id)
    if shipment is None:
        return False
    shipment.delivered = True
    shipment.delivery_notified = True
    shipment.last_error = None
    _apply_status(shipment.order, shipment)
    db.commit()
    return True


def update_order_destination(db: Session, order_id: int, dest_x: int, dest_y: int) -> Optional[OrderView]:
    order = _get_order(db, order_id)
    if order is None or order.shipment is None:
        return None
    order.dest_x = dest_x
    order.dest_y = dest_y
    db.commit()
    db.refresh(order)
    db.refresh(order.shipment)
    return _to_view(order, order.shipment)
