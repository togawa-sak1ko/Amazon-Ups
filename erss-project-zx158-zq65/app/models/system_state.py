from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PackageCounter(Base):
    __tablename__ = "package_counters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    next_value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)


class RuntimeState(Base):
    __tablename__ = "runtime_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    int_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
