from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.system_state import RuntimeState


def get_runtime_int(db: Session, key: str) -> Optional[int]:
    state = db.get(RuntimeState, key)
    if state is None:
        return None
    return state.int_value


def set_runtime_int(db: Session, key: str, value: Optional[int]) -> None:
    state = db.get(RuntimeState, key)
    if state is None:
        state = RuntimeState(key=key, int_value=value)
        db.add(state)
    else:
        state.int_value = value
    db.flush()
