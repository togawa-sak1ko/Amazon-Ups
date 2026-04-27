from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.auth_service import create_customer, get_customer_by_email, sign_in, sign_out, verify_customer

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, message: Optional[str] = None, next: str = "/") -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "auth.html",
        {
            "mode": "login",
            "message": message,
            "next_url": next,
        },
    )


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next_url: str = Form(default="/"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    customer = verify_customer(db, email, password)
    if customer is None:
        query = urlencode({"message": "Email or password is incorrect."})
        return RedirectResponse(url=f"/login?{query}", status_code=303)
    sign_in(request, customer)
    return RedirectResponse(url=next_url or "/", status_code=303)


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, message: Optional[str] = None) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "auth.html",
        {
            "mode": "register",
            "message": message,
            "next_url": "/",
        },
    )


@router.post("/register")
def register(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if len(password) < 6:
        query = urlencode({"message": "Password must be at least 6 characters."})
        return RedirectResponse(url=f"/register?{query}", status_code=303)
    if get_customer_by_email(db, email) is not None:
        query = urlencode({"message": "That email is already registered."})
        return RedirectResponse(url=f"/register?{query}", status_code=303)
    customer = create_customer(db, email, display_name, password)
    sign_in(request, customer)
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    sign_out(request)
    return RedirectResponse(url="/", status_code=303)
