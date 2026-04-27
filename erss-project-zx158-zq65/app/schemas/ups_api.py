from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class PickupRequest(BaseModel):
    package_id: int
    warehouse_id: int
    dest_x: int
    dest_y: int
    ups_username: Optional[str] = None


class PickupResponse(BaseModel):
    truck_id: int


class TruckArrivedRequest(BaseModel):
    truck_id: int
    warehouse_id: int
    package_id: int


class PackageLoadedRequest(BaseModel):
    package_id: int
    truck_id: int
    dest_x: int
    dest_y: int


class PackageDeliveredRequest(BaseModel):
    package_id: int


class RedirectRequest(BaseModel):
    package_id: int
    dest_x: int
    dest_y: int


class RedirectResponse(BaseModel):
    success: bool
    message: Optional[str] = None

