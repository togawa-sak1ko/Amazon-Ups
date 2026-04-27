from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Optional

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.customer import Customer


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    ).hex()


def get_customer_by_email(db: Session, email: str) -> Optional[Customer]:
    return db.scalar(select(Customer).where(Customer.email == _normalize_email(email)))


def get_customer(db: Session, customer_id: int) -> Optional[Customer]:
    return db.get(Customer, customer_id)


def create_customer(db: Session, email: str, display_name: str, password: str) -> Customer:
    salt = secrets.token_hex(16)
    customer = Customer(
        email=_normalize_email(email),
        display_name=display_name.strip() or _normalize_email(email).split("@")[0],
        password_salt=salt,
        password_hash=_hash_password(password, salt),
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def verify_customer(db: Session, email: str, password: str) -> Optional[Customer]:
    customer = get_customer_by_email(db, email)
    if customer is None:
        return None
    candidate = _hash_password(password, customer.password_salt)
    if not hmac.compare_digest(candidate, customer.password_hash):
        return None
    return customer


def current_customer(request: Request, db: Session) -> Optional[Customer]:
    customer_id = request.session.get("customer_id")
    if not isinstance(customer_id, int):
        return None
    return get_customer(db, customer_id)


def sign_in(request: Request, customer: Customer) -> None:
    request.session["customer_id"] = customer.id


def sign_out(request: Request) -> None:
    request.session.pop("customer_id", None)
