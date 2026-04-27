from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.cart import CartItem


def list_cart_items(db: Session, customer_id: int) -> list[CartItem]:
    stmt = (
        select(CartItem)
        .where(CartItem.customer_id == customer_id)
        .order_by(CartItem.created_at.desc())
    )
    return list(db.scalars(stmt))


def cart_item_count(db: Session, customer_id: int | None) -> int:
    if customer_id is None:
        return 0
    stmt = select(func.coalesce(func.sum(CartItem.quantity), 0)).where(CartItem.customer_id == customer_id)
    return int(db.scalar(stmt) or 0)


def add_to_cart(db: Session, customer_id: int, product_name: str, quantity: int) -> CartItem:
    normalized_name = product_name.strip()
    stmt = select(CartItem).where(
        CartItem.customer_id == customer_id,
        CartItem.product_name == normalized_name,
    )
    item = db.scalar(stmt)
    if item is None:
        item = CartItem(customer_id=customer_id, product_name=normalized_name, quantity=max(1, quantity))
        db.add(item)
    else:
        item.quantity += max(1, quantity)
    db.commit()
    db.refresh(item)
    return item


def remove_cart_item(db: Session, customer_id: int, item_id: int) -> bool:
    item = db.get(CartItem, item_id)
    if item is None or item.customer_id != customer_id:
        return False
    db.delete(item)
    db.commit()
    return True


def clear_cart(db: Session, customer_id: int) -> None:
    for item in list_cart_items(db, customer_id):
        db.delete(item)
    db.commit()
