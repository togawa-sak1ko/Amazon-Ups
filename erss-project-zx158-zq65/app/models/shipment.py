from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, unique=True)
    package_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    warehouse_id: Mapped[int] = mapped_column(Integer, nullable=False)
    truck_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    world_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    inventory_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    inventory_arrived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pack_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    packed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pickup_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    truck_arrived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    load_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    loaded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    delivery_notified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    order = relationship("Order", back_populates="shipment")
