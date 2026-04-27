from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.warehouse import InventoryItem


def list_catalog(db: Session, search: Optional[str] = None) -> list[InventoryItem]:
    stmt = select(InventoryItem).order_by(InventoryItem.product_name.asc())
    if search:
        stmt = stmt.where(InventoryItem.product_name.ilike(f"%{search.strip()}%"))
    return list(db.scalars(stmt))
