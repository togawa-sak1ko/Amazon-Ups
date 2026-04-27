from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.order import OrderCreate
from app.services.auth_service import current_customer
from app.services.cart_service import add_to_cart, cart_item_count, clear_cart, list_cart_items, remove_cart_item
from app.services.order_service import create_order

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _login_redirect(next_url: str, message: str = "Sign in to use your cart.") -> RedirectResponse:
    query = urlencode({"message": message, "next": next_url})
    return RedirectResponse(url=f"/login?{query}", status_code=303)


@router.get("/cart", response_class=HTMLResponse)
def cart_page(
    request: Request,
    message: Optional[str] = None,
    db: Session = Depends(get_db),
) -> Response:
    customer = current_customer(request, db)
    if customer is None:
        return _login_redirect("/cart")
    items = list_cart_items(db, customer.id)
    return templates.TemplateResponse(
        request,
        "cart.html",
        {
            "current_user": customer,
            "cart_items": items,
            "cart_count": cart_item_count(db, customer.id),
            "message": message,
        },
    )


@router.post("/cart/items")
def add_cart_item(
    request: Request,
    product_name: str = Form(...),
    quantity: int = Form(default=1),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    customer = current_customer(request, db)
    if customer is None:
        return _login_redirect("/", "Sign in or create an account before adding items to your cart.")
    add_to_cart(db, customer.id, product_name, quantity)
    query = urlencode({"message": f"{product_name} added to cart."})
    return RedirectResponse(url=f"/cart?{query}", status_code=303)


@router.post("/cart/items/{item_id}/delete")
def delete_cart_item(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    customer = current_customer(request, db)
    if customer is None:
        return _login_redirect("/cart")
    remove_cart_item(db, customer.id, item_id)
    return RedirectResponse(url="/cart", status_code=303)


@router.post("/cart/checkout")
def checkout_cart(
    request: Request,
    dest_x: int = Form(...),
    dest_y: int = Form(...),
    ups_username: str = Form(default=""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    customer = current_customer(request, db)
    if customer is None:
        return _login_redirect("/cart")
    items = list_cart_items(db, customer.id)
    if not items:
        query = urlencode({"message": "Your cart is empty."})
        return RedirectResponse(url=f"/cart?{query}", status_code=303)

    created_orders = []
    for item in items:
        created_orders.append(
            create_order(
                db,
                OrderCreate(
                    product_name=item.product_name,
                    quantity=item.quantity,
                    dest_x=dest_x,
                    dest_y=dest_y,
                    ups_username=ups_username or customer.email,
                ),
            )
        )
    clear_cart(db, customer.id)
    query = urlencode({"message": f"Cart checkout placed {len(created_orders)} order(s)."})
    return RedirectResponse(url=f"/orders/{created_orders[0].order_id}?{query}", status_code=303)
