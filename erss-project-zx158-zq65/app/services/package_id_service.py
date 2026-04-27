from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.system_state import PackageCounter


def next_package_id(db: Session) -> int:
    counter = db.get(PackageCounter, 1)
    if counter is None:
        counter = PackageCounter(id=1, next_value=2)
        db.add(counter)
        db.flush()
        return 1

    current = counter.next_value
    counter.next_value += 1
    db.flush()
    return current
