from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.order_service import get_order_by_package_id

router = APIRouter(prefix="/tracking", tags=["tracking"])


@router.get("")
def tracking_lookup(package_id: int = Query(...), db: Session = Depends(get_db)) -> dict[str, object]:
    order = get_order_by_package_id(db, package_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Package not found")
    return order.model_dump()

