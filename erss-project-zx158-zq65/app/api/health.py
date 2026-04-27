from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.runtime_state_service import get_runtime_int

router = APIRouter()


@router.get("/healthz")
def healthcheck(db: Session = Depends(get_db)) -> dict[str, object]:
    return {
        "status": "ok",
        "world_id": get_runtime_int(db, "world_id"),
    }
