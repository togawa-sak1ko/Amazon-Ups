from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    product_name: str = Field(min_length=1, max_length=120)
    quantity: int = Field(ge=1, le=1000)
    dest_x: int
    dest_y: int
    ups_username: Optional[str] = Field(default=None, max_length=120)


class OrderView(BaseModel):
    order_id: int
    package_id: int
    product_name: str
    quantity: int
    dest_x: int
    dest_y: int
    status: str
    warehouse_id: int
    truck_id: Optional[int]
    ups_username: Optional[str]
    last_error: Optional[str]

