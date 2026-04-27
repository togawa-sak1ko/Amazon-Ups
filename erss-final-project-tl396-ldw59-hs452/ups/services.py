import math
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .amazon_client import AmazonHttpClient, AmazonProtocolError
from .models import (
    Shipment,
    ShipmentEvent,
    ShipmentItem,
    ShipmentStatus,
    SavedQuote,
    SupportTicket,
    Truck,
    TruckStatus,
    WorldCommand,
    WorldCommandStatus,
    WorldSession,
)


User = get_user_model()


SERVICE_LOCATIONS = [
    {
        "name": "Durham Customer Center",
        "city": "Durham",
        "state": "NC",
        "postal_code": "27701",
        "type": "Customer Center",
        "services": ["Drop Off", "Pickup", "Tracking Help"],
    },
    {
        "name": "Research Triangle Hub",
        "city": "Morrisville",
        "state": "NC",
        "postal_code": "27560",
        "type": "Distribution Hub",
        "services": ["Sorting", "Warehouse Transfers", "Truck Dispatch"],
    },
    {
        "name": "Chapel Hill Access Point",
        "city": "Chapel Hill",
        "state": "NC",
        "postal_code": "27514",
        "type": "Access Point",
        "services": ["Drop Off", "Will Call"],
    },
    {
        "name": "Raleigh Operations Center",
        "city": "Raleigh",
        "state": "NC",
        "postal_code": "27601",
        "type": "Operations Center",
        "services": ["Customer Support", "Dispatch", "Service Alerts"],
    },
    {
        "name": "Cary Pickup Counter",
        "city": "Cary",
        "state": "NC",
        "postal_code": "27511",
        "type": "Pickup Counter",
        "services": ["Pickup", "Signature Hold", "Delivery Change Help"],
    },
]


PORTAL_PAGES = [
    {
        "title": "Tracking",
        "description": "Track packages, inspect status, and move into the shipment workspace.",
        "url_name": "ups:home",
    },
    {
        "title": "Shipping",
        "description": "Prepare shipments, coordinate service options, and review shipping tools.",
        "url_name": "ups:shipping-overview",
    },
    {
        "title": "Quote",
        "description": "Estimate rates and delivery timing for different service levels.",
        "url_name": "ups:quote-overview",
    },
    {
        "title": "Support",
        "description": "Open support requests and browse help-center actions.",
        "url_name": "ups:support-center",
    },
    {
        "title": "Alerts",
        "description": "Review recent shipment events and open support items.",
        "url_name": "ups:alerts-center",
    },
    {
        "title": "Locations",
        "description": "Find customer centers, hubs, and access points.",
        "url_name": "ups:locations-center",
    },
]


def generate_tracking_number() -> str:
    return f"UPS-{uuid4().hex[:10].upper()}"


def get_or_create_world_session(world_id=None) -> WorldSession:
    if world_id:
        session, _ = WorldSession.objects.get_or_create(
            world_id=world_id,
            defaults={"name": f"world-{world_id}"},
        )
        return session
    session, _ = WorldSession.objects.get_or_create(name="primary")
    return session


def next_sequence_number(world_session: WorldSession) -> int:
    with transaction.atomic():
        session = WorldSession.objects.select_for_update().get(pk=world_session.pk)
        seq_num = session.next_seq_num
        session.next_seq_num += 1
        session.save(update_fields=["next_seq_num"])
        return seq_num


def queue_world_command(world_session: WorldSession, command_type: str, payload: dict, shipment=None, truck=None):
    seq_num = next_sequence_number(world_session)
    return WorldCommand.objects.create(
        world_session=world_session,
        shipment=shipment,
        truck=truck,
        seq_num=seq_num,
        command_type=command_type,
        payload=payload,
    )


def choose_truck(world_session: WorldSession, requested_truck_id=None):
    trucks = list(world_session.trucks.all())
    if requested_truck_id is not None:
        for truck in trucks:
            if truck.truck_id == requested_truck_id:
                return truck
        return None

    priority = {
        TruckStatus.IDLE: 0,
        TruckStatus.ARRIVED_WAREHOUSE: 1,
        TruckStatus.TRAVELING: 2,
        TruckStatus.LOADING: 3,
        TruckStatus.DELIVERING: 4,
    }
    trucks.sort(key=lambda truck: (priority.get(truck.status, 99), truck.truck_id))
    return trucks[0] if trucks else None


def _payload_value(payload, *keys):
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def create_shipment_from_amazon(payload: dict) -> Shipment:
    destination_x = _payload_value(payload, "destination_x", "dest_x")
    destination_y = _payload_value(payload, "destination_y", "dest_y")
    owner_reference = _payload_value(payload, "owner_username", "ups_username") or ""
    if destination_x is not None:
        payload["destination_x"] = destination_x
    if destination_y is not None:
        payload["destination_y"] = destination_y

    required = {"package_id", "warehouse_id", "destination_x", "destination_y"}
    missing = {field for field in required if field not in payload}
    if missing:
        missing_fields = ", ".join(sorted(missing))
        raise ValueError(f"Missing required shipment fields: {missing_fields}")

    package_id = int(payload["package_id"])
    tracking_number = payload.get("tracking_number") or str(package_id)
    world_session = get_or_create_world_session(payload.get("world_id"))

    with transaction.atomic():
        shipment, created = Shipment.objects.select_for_update().get_or_create(
            package_id=package_id,
            defaults={
                "world_session": world_session,
                "tracking_number": tracking_number,
                "owner_reference": owner_reference,
                "warehouse_id": int(payload["warehouse_id"]),
                "origin_x": int(payload.get("origin_x", 0)),
                "origin_y": int(payload.get("origin_y", 0)),
                "destination_x": int(payload["destination_x"]),
                "destination_y": int(payload["destination_y"]),
                "amazon_order_reference": payload.get("amazon_order_reference", ""),
            },
        )

        if not created:
            shipment.world_session = world_session
            shipment.owner_reference = owner_reference or shipment.owner_reference
            shipment.destination_x = int(payload["destination_x"])
            shipment.destination_y = int(payload["destination_y"])
            shipment.amazon_order_reference = payload.get(
                "amazon_order_reference", shipment.amazon_order_reference
            )
            if shipment.assigned_truck_id is None and payload.get("truck_id") is not None:
                truck = choose_truck(world_session, requested_truck_id=payload["truck_id"])
                if truck is not None:
                    shipment.assigned_truck = truck

        shipment.assign_owner_from_reference()
        shipment.save()

        items = payload.get("items", [])
        if items:
            shipment.items.all().delete()
            ShipmentItem.objects.bulk_create(
                [
                    ShipmentItem(
                        shipment=shipment,
                        sku=item.get("sku", ""),
                        description=item.get("description", "Unknown item"),
                        quantity=int(item.get("quantity", 1)),
                    )
                    for item in items
                ]
            )

        ShipmentEvent.objects.create(
            shipment=shipment,
            event_type="shipment_registered",
            message="Shipment intake received from Amazon/IG integration layer.",
            metadata={"created": created},
        )

        if payload.get("queue_pickup", True):
            queue_pickup_command(shipment, requested_truck_id=payload.get("truck_id"))

    return shipment


def queue_pickup_command(shipment: Shipment, requested_truck_id=None):
    if shipment.world_session is None:
        shipment.world_session = get_or_create_world_session()
        shipment.save(update_fields=["world_session"])

    truck = choose_truck(shipment.world_session, requested_truck_id=requested_truck_id)
    if truck is None:
        raise ValueError("No truck is available to service this shipment yet.")

    payload = {
        "truck_id": truck.truck_id,
        "warehouse_id": shipment.warehouse_id,
        "package_id": shipment.package_id,
    }
    command = queue_world_command(
        shipment.world_session,
        "pickup",
        payload,
        shipment=shipment,
        truck=truck,
    )
    shipment.assigned_truck = truck
    shipment.status = ShipmentStatus.EN_ROUTE_TO_WAREHOUSE
    shipment.save(update_fields=["assigned_truck", "status", "updated_at"])
    ShipmentEvent.objects.create(
        shipment=shipment,
        event_type="pickup_queued",
        message=f"Queued pickup request for truck {truck.truck_id}.",
        metadata={"seq_num": command.seq_num},
    )
    return command


def queue_delivery_command(shipment: Shipment):
    if shipment.assigned_truck is None:
        raise ValueError("A truck must be assigned before delivery can be queued.")
    if shipment.world_session is None:
        raise ValueError("A world session is required before delivery can be queued.")

    payload = {
        "truck_id": shipment.assigned_truck.truck_id,
        "package_id": shipment.package_id,
        "destination_x": shipment.destination_x,
        "destination_y": shipment.destination_y,
    }
    command = queue_world_command(
        shipment.world_session,
        "deliver",
        payload,
        shipment=shipment,
        truck=shipment.assigned_truck,
    )
    shipment.status = ShipmentStatus.OUT_FOR_DELIVERY
    shipment.save(update_fields=["status", "updated_at"])
    ShipmentEvent.objects.create(
        shipment=shipment,
        event_type="delivery_queued",
        message=f"Queued delivery request for truck {shipment.assigned_truck.truck_id}.",
        metadata={"seq_num": command.seq_num},
    )
    return command


def notify_amazon_truck_arrived(shipment: Shipment):
    if shipment.assigned_truck is None:
        raise ValueError("Truck arrival cannot be announced without an assigned truck.")
    client = AmazonHttpClient()
    return client.notify_truck_arrived(shipment)


def notify_amazon_package_delivered(shipment: Shipment):
    client = AmazonHttpClient()
    return client.notify_package_delivered(shipment)


def notify_amazon_truck_arrived_for_waiting_shipment(shipment: Shipment) -> bool:
    try:
        notify_amazon_truck_arrived(shipment)
    except AmazonProtocolError as exc:
        ShipmentEvent.objects.create(
            shipment=shipment,
            event_type="amazon_callback_failed",
            message=f"Failed to notify Amazon of truck arrival: {exc}",
        )
        return False
    ShipmentEvent.objects.create(
        shipment=shipment,
        event_type="amazon_truck_arrived_notified",
        message="Amazon notified that the truck arrived at the warehouse.",
    )
    return True


def mark_shipment_waiting(shipment: Shipment, truck: Truck, notify_amazon=True):
    shipment.assigned_truck = truck
    shipment.status = ShipmentStatus.WAITING_FOR_PICKUP
    shipment.save(update_fields=["assigned_truck", "status", "updated_at"])
    ShipmentEvent.objects.create(
        shipment=shipment,
        event_type="truck_waiting",
        message=f"Truck {truck.truck_id} is waiting for the package to be loaded.",
    )
    if notify_amazon:
        notify_amazon_truck_arrived_for_waiting_shipment(shipment)


def mark_shipment_loaded(shipment: Shipment, auto_queue_delivery=True):
    shipment.status = ShipmentStatus.LOADED
    shipment.save(update_fields=["status", "updated_at"])
    ShipmentEvent.objects.create(
        shipment=shipment,
        event_type="shipment_loaded",
        message="Amazon reported that the package has been loaded onto the truck.",
    )
    if auto_queue_delivery:
        queue_delivery_command(shipment)


def mark_shipment_delivered(shipment: Shipment, notify_amazon=True):
    shipment.status = ShipmentStatus.DELIVERED
    shipment.delivered_at = timezone.now()
    shipment.save(update_fields=["status", "delivered_at", "updated_at"])
    ShipmentEvent.objects.create(
        shipment=shipment,
        event_type="shipment_delivered",
        message="World simulator confirmed delivery.",
    )
    if notify_amazon:
        try:
            notify_amazon_package_delivered(shipment)
        except AmazonProtocolError as exc:
            ShipmentEvent.objects.create(
                shipment=shipment,
                event_type="amazon_callback_failed",
                message=f"Failed to notify Amazon of delivery completion: {exc}",
            )
        else:
            ShipmentEvent.objects.create(
                shipment=shipment,
                event_type="amazon_delivery_notified",
                message="Amazon notified that the package was delivered.",
            )


def redirect_shipment(shipment: Shipment, destination_x: int, destination_y: int, actor="user"):
    if not shipment.can_redirect():
        raise ValueError("This shipment can no longer be redirected.")

    shipment.destination_x = int(destination_x)
    shipment.destination_y = int(destination_y)
    shipment.save(update_fields=["destination_x", "destination_y", "updated_at"])
    ShipmentEvent.objects.create(
        shipment=shipment,
        event_type="shipment_redirected",
        message=f"Shipment redirected to ({destination_x}, {destination_y}).",
        metadata={"actor": actor},
    )
    return shipment


def mark_loaded_from_amazon(package_id: int, truck_id: int, destination_x: int, destination_y: int):
    shipment = Shipment.objects.select_related("assigned_truck", "world_session").get(package_id=package_id)
    if shipment.assigned_truck_id is None:
        if shipment.world_session is None:
            raise ValueError("Shipment is missing an active world session.")
        truck = choose_truck(shipment.world_session, requested_truck_id=truck_id)
        if truck is None:
            raise ValueError("Unknown truck_id for this world session.")
        shipment.assigned_truck = truck
    elif shipment.assigned_truck.truck_id != int(truck_id):
        raise ValueError("Truck ID does not match the truck assigned by UPS.")

    shipment.destination_x = int(destination_x)
    shipment.destination_y = int(destination_y)
    shipment.save(update_fields=["assigned_truck", "destination_x", "destination_y", "updated_at"])
    mark_shipment_loaded(shipment, auto_queue_delivery=True)
    return shipment


def visible_shipments_for_user(user):
    queryset = Shipment.objects.select_related("assigned_truck", "owner").prefetch_related("items", "events")
    if user.is_staff:
        return queryset
    return queryset.filter(Q(owner=user) | Q(owner_reference__iexact=user.username))


def sync_truck_state(world_session: WorldSession, truck_id: int, status: str, current_x: int, current_y: int):
    truck, _ = Truck.objects.get_or_create(
        world_session=world_session,
        truck_id=truck_id,
        defaults={"status": TruckStatus.IDLE},
    )
    truck.status = status
    truck.current_x = current_x
    truck.current_y = current_y
    truck.save(update_fields=["status", "current_x", "current_y", "updated_at"])
    return truck


def acknowledge_world_command(command: WorldCommand):
    command.status = WorldCommandStatus.ACKED
    command.acked_at = timezone.now()
    command.save(update_fields=["status", "acked_at", "updated_at"])


def record_world_command_error(command: WorldCommand, err: str) -> bool:
    """Apply a simulator UErr to a queued command.

    Increments retry_count for this failure. While under the configured cap, moves the row
    back to PENDING so the daemon can resend the same seq_num. Otherwise leaves FAILED.

    Returns:
        True if the command was requeued for another attempt, False if this failure is terminal.
    """
    max_retries = getattr(settings, "UPS_WORLD_COMMAND_MAX_RETRIES", 5)
    command.last_error = err
    command.retry_count += 1
    if command.retry_count <= max_retries:
        command.status = WorldCommandStatus.PENDING
        command.save(update_fields=["status", "last_error", "retry_count", "updated_at"])
        return True
    command.status = WorldCommandStatus.FAILED
    command.save(update_fields=["status", "last_error", "retry_count", "updated_at"])
    return False


def calculate_quote(cleaned_data: dict) -> dict:
    distance = abs(cleaned_data["destination_x"] - cleaned_data["origin_x"]) + abs(
        cleaned_data["destination_y"] - cleaned_data["origin_y"]
    )
    service_level = cleaned_data["service_level"]
    package_count = cleaned_data["package_count"]
    total_weight = float(cleaned_data["total_weight_lbs"])

    service_multiplier = {
        "ground": 1.0,
        "two_day": 1.42,
        "express": 1.95,
    }[service_level]
    delivery_days = {
        "ground": max(1, math.ceil(distance / 12)),
        "two_day": min(2, max(1, math.ceil(distance / 18))),
        "express": 1,
    }[service_level]

    base_cents = 895 + distance * 38 + package_count * 140 + int(total_weight * 82)
    estimated_cost_cents = int(base_cents * service_multiplier)
    estimated_surcharge_cents = int(max(0, distance - 10) * 18)

    return {
        "service_level": service_level,
        "origin_x": cleaned_data["origin_x"],
        "origin_y": cleaned_data["origin_y"],
        "destination_x": cleaned_data["destination_x"],
        "destination_y": cleaned_data["destination_y"],
        "package_count": package_count,
        "total_weight_lbs": cleaned_data["total_weight_lbs"],
        "distance": distance,
        "estimated_business_days": delivery_days,
        "estimated_cost_cents": estimated_cost_cents,
        "estimated_cost_display": f"${estimated_cost_cents / 100:.2f}",
        "estimated_surcharge_display": f"${estimated_surcharge_cents / 100:.2f}",
    }


def save_quote(cleaned_data: dict, user=None) -> SavedQuote:
    result = calculate_quote(cleaned_data)
    return SavedQuote.objects.create(
        created_by=user if getattr(user, "is_authenticated", False) else None,
        service_level=result["service_level"],
        origin_x=result["origin_x"],
        origin_y=result["origin_y"],
        destination_x=result["destination_x"],
        destination_y=result["destination_y"],
        package_count=result["package_count"],
        total_weight_lbs=result["total_weight_lbs"],
        estimated_cost_cents=result["estimated_cost_cents"],
        estimated_business_days=result["estimated_business_days"],
    )


def create_support_ticket(cleaned_data: dict, user=None) -> SupportTicket:
    return SupportTicket.objects.create(
        owner=user if getattr(user, "is_authenticated", False) else None,
        email=cleaned_data["email"],
        tracking_number=cleaned_data.get("tracking_number", ""),
        category=cleaned_data["category"],
        subject=cleaned_data["subject"],
        message=cleaned_data["message"],
    )


def build_alert_feed(user=None):
    if getattr(user, "is_authenticated", False):
        shipments = visible_shipments_for_user(user)
        tickets = SupportTicket.objects.filter(Q(owner=user) | Q(email__iexact=user.email))
    else:
        shipments = Shipment.objects.all()
        tickets = SupportTicket.objects.none()

    shipment_events = (
        ShipmentEvent.objects.select_related("shipment")
        .filter(shipment__in=shipments)
        .order_by("-created_at")[:20]
    )

    feed = [
        {
            "kind": "shipment",
            "title": f"{event.shipment.tracking_number}: {event.event_type.replace('_', ' ').title()}",
            "message": event.message,
            "created_at": event.created_at,
        }
        for event in shipment_events
    ]
    feed.extend(
        {
            "kind": "support",
            "title": ticket.subject,
            "message": f"{ticket.get_category_display()} ticket is {ticket.get_status_display().lower()}.",
            "created_at": ticket.updated_at,
        }
        for ticket in tickets.order_by("-updated_at")[:10]
    )
    feed.sort(key=lambda item: item["created_at"], reverse=True)
    return feed[:25]


def get_service_locations(query=""):
    normalized = query.strip().lower()
    if not normalized:
        return SERVICE_LOCATIONS

    def matches(location):
        haystack = " ".join(
            [
                location["name"],
                location["city"],
                location["state"],
                location["postal_code"],
                location["type"],
                " ".join(location["services"]),
            ]
        ).lower()
        return normalized in haystack

    return [location for location in SERVICE_LOCATIONS if matches(location)]


def portal_search(query, user=None):
    normalized = query.strip()
    shipment_filter = (
        Q(tracking_number__icontains=normalized)
        | Q(owner_reference__icontains=normalized)
        | Q(amazon_order_reference__icontains=normalized)
    )
    if normalized.isdigit():
        shipment_filter |= Q(package_id=int(normalized))

    shipments = Shipment.objects.select_related("assigned_truck").filter(shipment_filter).order_by("-updated_at")[:10]
    if getattr(user, "is_authenticated", False) and not user.is_staff:
        shipments = visible_shipments_for_user(user).filter(
            Q(tracking_number__icontains=normalized)
            | Q(owner_reference__icontains=normalized)
            | Q(amazon_order_reference__icontains=normalized)
            | (Q(package_id=int(normalized)) if normalized.isdigit() else Q())
        )[:10]

    page_matches = [
        page
        for page in PORTAL_PAGES
        if normalized.lower() in page["title"].lower() or normalized.lower() in page["description"].lower()
    ]

    return {
        "shipments": shipments,
        "locations": get_service_locations(normalized)[:6],
        "page_matches": page_matches,
    }
