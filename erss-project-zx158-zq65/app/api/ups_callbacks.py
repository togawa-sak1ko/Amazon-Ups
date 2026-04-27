from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.ups_api import PackageDeliveredRequest, TruckArrivedRequest
from app.services.order_service import mark_delivered, mark_truck_arrived

router = APIRouter(tags=["ups"])


@router.post("/truck-arrived", status_code=status.HTTP_200_OK)
def truck_arrived(payload: TruckArrivedRequest, db: Session = Depends(get_db)) -> Response:
    updated = mark_truck_arrived(db, payload.package_id, payload.truck_id, payload.warehouse_id)
    if not updated:
        return JSONResponse(status_code=404, content={"error": "Package not found"})
    return Response(content="{}", media_type="application/json")


@router.post("/package-delivered", status_code=status.HTTP_200_OK)
def package_delivered(payload: PackageDeliveredRequest, db: Session = Depends(get_db)) -> Response:
    updated = mark_delivered(db, payload.package_id)
    if not updated:
        return JSONResponse(status_code=404, content={"error": "Package not found"})
    return Response(content="{}", media_type="application/json")
