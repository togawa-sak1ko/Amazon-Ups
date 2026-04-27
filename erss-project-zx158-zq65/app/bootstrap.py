from sqlalchemy import select, text

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.models.order import Order
from app.models.shipment import Shipment
from app.models.system_state import PackageCounter, RuntimeState
from app.models.warehouse import Warehouse
from app.models.warehouse import InventoryItem


def bootstrap() -> None:
    settings = get_settings()
    _ = (Order, Shipment, InventoryItem, PackageCounter, RuntimeState)
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_lock(104729)"))
        try:
            Base.metadata.create_all(bind=conn)
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(104729)"))

    with SessionLocal() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(104729)"))

        counter = db.get(PackageCounter, 1)
        if counter is None:
            db.add(PackageCounter(id=1, next_value=1))

        world_state = db.get(RuntimeState, "world_id")
        if world_state is None:
            db.add(RuntimeState(key="world_id", int_value=settings.world_id))
        elif settings.world_id is not None:
            world_state.int_value = settings.world_id

        existing = db.scalar(select(Warehouse).where(Warehouse.id == settings.warehouse_id))
        if existing is None:
            db.add(
                Warehouse(
                    id=settings.warehouse_id,
                    x=settings.warehouse_x,
                    y=settings.warehouse_y,
                    name=f"Warehouse {settings.warehouse_id}",
                )
            )

        seeded_products = [
            "Widget",
            "Laptop Stand",
            "Mechanical Keyboard",
            "Studio Headphones",
            "Portable Monitor",
        ]
        for product_name in seeded_products:
            item = db.scalar(
                select(InventoryItem).where(
                    InventoryItem.warehouse_id == settings.warehouse_id,
                    InventoryItem.product_name == product_name,
                )
            )
            if item is None:
                db.add(
                    InventoryItem(
                        warehouse_id=settings.warehouse_id,
                        product_name=product_name,
                        quantity=0,
                    )
                )
        db.commit()


if __name__ == "__main__":
    bootstrap()
