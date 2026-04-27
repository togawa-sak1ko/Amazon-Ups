from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class OrderStatus(str, Enum):
    CREATED = "created"
    PACKING_REQUESTED = "packing_requested"
    PACKED = "packed"
    PICKUP_REQUESTED = "pickup_requested"
    TRUCK_ARRIVED = "truck_arrived"
    LOADING_REQUESTED = "loading_requested"
    LOADED = "loaded"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    FAILED = "failed"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_name: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    dest_x: Mapped[int] = mapped_column(Integer, nullable=False)
    dest_y: Mapped[int] = mapped_column(Integer, nullable=False)
    ups_username: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default=OrderStatus.CREATED.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    shipment = relationship("Shipment", back_populates="order", uselist=False)

