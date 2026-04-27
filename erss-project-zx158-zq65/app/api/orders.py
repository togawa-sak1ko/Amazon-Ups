from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.order import OrderCreate, OrderView
from app.schemas.ups_api import RedirectRequest
from app.integrations.ups_client import UPSClient, UPSClientError
from app.services.auth_service import current_customer
from app.services.cart_service import cart_item_count
from app.services.catalog_service import list_catalog
from app.services.order_service import (
    count_orders_by_status,
    create_order,
    get_order,
    list_recent_orders,
    update_order_destination,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

STATUS_FLOW = [
    "created",
    "pickup_requested",
    "packing_requested",
    "packed",
    "truck_arrived",
    "loading_requested",
    "loaded",
    "out_for_delivery",
    "delivered",
]

STATUS_LABELS = {
    "created": "Order placed",
    "pickup_requested": "UPS pickup requested",
    "packing_requested": "Preparing items",
    "packed": "Packed at warehouse",
    "truck_arrived": "Truck arrived",
    "loading_requested": "Loading package",
    "loaded": "Loaded on truck",
    "out_for_delivery": "Out for delivery",
    "delivered": "Delivered",
    "failed": "Needs attention",
}

STATUS_DESCRIPTIONS = {
    "created": "Amazon accepted the customer order and created a package id.",
    "pickup_requested": "Amazon requested a UPS truck for this warehouse pickup.",
    "packing_requested": "Inventory has been requested from the simulated world.",
    "packed": "The package is packed and ready for truck arrival.",
    "truck_arrived": "UPS has arrived at the warehouse.",
    "loading_requested": "Amazon asked the world to load the package onto the truck.",
    "loaded": "The package is physically loaded in the world simulator.",
    "out_for_delivery": "UPS has been notified that delivery can begin.",
    "delivered": "UPS confirmed final delivery to the destination.",
}


def _status_index(status: str) -> int:
    if status == "failed":
        return 0
    try:
        return STATUS_FLOW.index(status)
    except ValueError:
        return 0


def _status_percent(status: str) -> int:
    if status == "failed":
        return 12
    if status == "delivered":
        return 100
    return max(12, int((_status_index(status) / (len(STATUS_FLOW) - 1)) * 100))


def _decorate_order(order: OrderView) -> dict[str, object]:
    data = order.model_dump()
    data["status_label"] = STATUS_LABELS.get(data["status"], data["status"])
    return data


def _timeline_for(status: str) -> list[dict[str, object]]:
    current_step = _status_index(status)
    return [
        {
            "key": step,
            "label": STATUS_LABELS.get(step, step),
            "description": STATUS_DESCRIPTIONS[step],
            "complete": status != "failed" and index <= current_step,
            "failed": status == "failed" and index == 0,
        }
        for index, step in enumerate(STATUS_FLOW)
    ]


@router.get("/", response_class=HTMLResponse)
def order_form(
    request: Request,
    q: Optional[str] = None,
    message: Optional[str] = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    catalog = list_catalog(db, q)
    recent_orders = list_recent_orders(db)
    status_counts = count_orders_by_status(db)
    customer = current_customer(request, db)
    active_orders = sum(
        count
        for status, count in status_counts.items()
        if status not in {"delivered", "failed"}
    )
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "catalog": catalog,
            "search": q or "",
            "recent_orders": [_decorate_order(order) for order in recent_orders],
            "status_counts": status_counts,
            "total_orders": sum(status_counts.values()),
            "active_orders": active_orders,
            "delivered_orders": status_counts.get("delivered", 0),
            "current_user": customer,
            "cart_count": cart_item_count(db, customer.id if customer else None),
            "message": message,
        },
    )


@router.post("/orders")
def submit_order(
    product_name: str = Form(...),
    quantity: int = Form(...),
    dest_x: int = Form(...),
    dest_y: int = Form(...),
    ups_username: str = Form(default=""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    payload = OrderCreate(
        product_name=product_name,
        quantity=quantity,
        dest_x=dest_x,
        dest_y=dest_y,
        ups_username=ups_username or None,
    )
    order = create_order(db, payload)
    return RedirectResponse(url=f"/orders/{order.order_id}", status_code=303)


@router.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(
    order_id: int,
    request: Request,
    message: Optional[str] = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    order = get_order(db, order_id)
    if order is None:
        return templates.TemplateResponse(
            request,
            "order_missing.html",
            {
                "order_id": order_id,
                "message": "That order was not found. If you just checked out, return to the storefront and try the recent orders list.",
            },
            status_code=404,
        )
    customer = current_customer(request, db)
    return templates.TemplateResponse(
        request,
        "order_detail.html",
        {
            "order": _decorate_order(order),
            "message": message,
            "timeline": _timeline_for(order.status),
            "status_percent": _status_percent(order.status),
            "current_user": customer,
            "cart_count": cart_item_count(db, customer.id if customer else None),
        },
    )


@router.post("/orders/{order_id}/redirect")
def redirect_order(
    order_id: int,
    dest_x: int = Form(...),
    dest_y: int = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    order = get_order(db, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    message = "Destination updated."

    def _redirect(message_text: str) -> RedirectResponse:
        query = urlencode({"message": message_text})
        return RedirectResponse(url=f"/orders/{order_id}?{query}", status_code=303)

    if order.status in {"delivered", "failed"}:
        return _redirect("Destination can no longer be changed for this order.")

    if order.status != "created":
        client = UPSClient()
        try:
            result = client.redirect_package(
                RedirectRequest(
                    package_id=order.package_id,
                    dest_x=dest_x,
                    dest_y=dest_y,
                )
            )
        except UPSClientError as exc:
            message = f"Redirect request failed: {exc}"
            return _redirect(message)
        if not result.success:
            message = result.message or "UPS rejected the redirect."
            return _redirect(message)

    update_order_destination(db, order_id, dest_x, dest_y)
    return _redirect(message)
