from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from ups.models import (
    QuoteServiceLevel,
    SavedQuote,
    Shipment,
    ShipmentEvent,
    ShipmentItem,
    ShipmentStatus,
    SupportTicket,
    SupportTicketCategory,
    SupportTicketStatus,
    Truck,
    TruckStatus,
    WorldSession,
)


User = get_user_model()


class Command(BaseCommand):
    help = "Seed deterministic mock portal data so Mini-UPS can be tested before Mini-Amazon integration is ready."

    def add_arguments(self, parser):
        parser.add_argument(
            "--session",
            default="mock-portal",
            help="WorldSession.name to create or use for seeded mock data.",
        )
        parser.add_argument(
            "--password",
            default="demo-pass-123",
            help="Password to apply to all mock users so sign-in can be tested quickly.",
        )

    def handle(self, *args, **options):
        password = options["password"]
        session_name = options["session"]
        timestamp = timezone.now()

        users = {
            "demo_customer": self._ensure_user("demo_customer", "demo_customer@example.com", password),
            "demo_receiver": self._ensure_user("demo_receiver", "demo_receiver@example.com", password),
        }
        demo_users = list(users.values())

        session, _ = WorldSession.objects.get_or_create(
            name=session_name,
            defaults={
                "world_id": 9901,
                "host": settings.UPS_WORLD_HOST,
                "port": settings.UPS_WORLD_PORT,
            },
        )
        if session.world_id is None:
            session.world_id = 9901
            session.host = settings.UPS_WORLD_HOST
            session.port = settings.UPS_WORLD_PORT
            session.save(update_fields=["world_id", "host", "port", "updated_at"])

        trucks = {
            21: self._ensure_truck(session, 21, TruckStatus.TRAVELING, 2, 3, "Warehouse 4 pickup"),
            22: self._ensure_truck(session, 22, TruckStatus.LOADING, 6, 5, "Warehouse 8 load"),
            23: self._ensure_truck(session, 23, TruckStatus.DELIVERING, 11, 9, "Final-mile run"),
        }

        shipment_specs = [
            {
                "package_id": 610001,
                "tracking_number": "610001",
                "owner": users["demo_customer"],
                "owner_reference": "demo_customer",
                "warehouse_id": 4,
                "destination_x": 12,
                "destination_y": 8,
                "assigned_truck": trucks[21],
                "status": ShipmentStatus.EN_ROUTE_TO_WAREHOUSE,
                "amazon_order_reference": "AMZ-MOCK-1001",
                "items": [
                    {"sku": "BK-100", "description": "Bookshelf anchors", "quantity": 2},
                    {"sku": "TB-204", "description": "Tablet sleeve", "quantity": 1},
                ],
                "events": [
                    ("shipment_registered", "Shipment intake received from mock portal seed data."),
                    ("pickup_queued", "Queued pickup request for truck 21."),
                ],
            },
            {
                "package_id": 610002,
                "tracking_number": "UPS-MOCK-LOAD",
                "owner": users["demo_customer"],
                "owner_reference": "demo_customer",
                "warehouse_id": 8,
                "destination_x": 14,
                "destination_y": 3,
                "assigned_truck": trucks[22],
                "status": ShipmentStatus.LOADING,
                "amazon_order_reference": "AMZ-MOCK-1002",
                "items": [
                    {"sku": "KT-778", "description": "Kitchen scale", "quantity": 1},
                    {"sku": "MN-310", "description": "Memory notebook", "quantity": 3},
                ],
                "events": [
                    ("shipment_registered", "Shipment intake received from mock portal seed data."),
                    ("truck_waiting", "Truck 22 is waiting for the package to be loaded."),
                    ("loading_started", "Warehouse staff started loading the parcel."),
                ],
            },
            {
                "package_id": 610003,
                "tracking_number": "UPS-MOCK-ROUTE",
                "owner": users["demo_receiver"],
                "owner_reference": "demo_receiver",
                "warehouse_id": 2,
                "destination_x": 18,
                "destination_y": 11,
                "assigned_truck": trucks[23],
                "status": ShipmentStatus.OUT_FOR_DELIVERY,
                "amazon_order_reference": "AMZ-MOCK-1003",
                "items": [
                    {"sku": "HD-040", "description": "Headphones", "quantity": 1},
                ],
                "events": [
                    ("shipment_registered", "Shipment intake received from mock portal seed data."),
                    ("shipment_loaded", "Package loaded onto truck 23."),
                    ("delivery_queued", "Queued delivery request for truck 23."),
                ],
            },
            {
                "package_id": 610004,
                "tracking_number": "UPS-MOCK-DONE",
                "owner": users["demo_customer"],
                "owner_reference": "demo_customer",
                "warehouse_id": 6,
                "destination_x": 5,
                "destination_y": 16,
                "assigned_truck": trucks[23],
                "status": ShipmentStatus.DELIVERED,
                "amazon_order_reference": "AMZ-MOCK-1004",
                "items": [
                    {"sku": "OF-901", "description": "Office lamp", "quantity": 1},
                ],
                "events": [
                    ("shipment_registered", "Shipment intake received from mock portal seed data."),
                    ("shipment_loaded", "Package loaded onto truck 23."),
                    ("shipment_delivered", "World simulator confirmed delivery."),
                ],
            },
        ]

        created_shipments = []
        for spec in shipment_specs:
            shipment, _ = Shipment.objects.update_or_create(
                package_id=spec["package_id"],
                defaults={
                    "world_session": session,
                    "tracking_number": spec["tracking_number"],
                    "owner": spec["owner"],
                    "owner_reference": spec["owner_reference"],
                    "warehouse_id": spec["warehouse_id"],
                    "origin_x": 0,
                    "origin_y": 0,
                    "destination_x": spec["destination_x"],
                    "destination_y": spec["destination_y"],
                    "assigned_truck": spec["assigned_truck"],
                    "status": spec["status"],
                    "amazon_order_reference": spec["amazon_order_reference"],
                    "delivered_at": timestamp if spec["status"] == ShipmentStatus.DELIVERED else None,
                },
            )
            shipment.items.all().delete()
            shipment.events.all().delete()
            ShipmentItem.objects.bulk_create(
                [
                    ShipmentItem(
                        shipment=shipment,
                        sku=item["sku"],
                        description=item["description"],
                        quantity=item["quantity"],
                    )
                    for item in spec["items"]
                ]
            )
            for event_type, message in spec["events"]:
                ShipmentEvent.objects.create(shipment=shipment, event_type=event_type, message=message)
            created_shipments.append(shipment)

        SupportTicket.objects.filter(owner__in=demo_users).delete()
        SavedQuote.objects.filter(created_by__in=demo_users).delete()

        SupportTicket.objects.create(
            owner=users["demo_customer"],
            email=users["demo_customer"].email,
            tracking_number="610001",
            category=SupportTicketCategory.TRACKING,
            subject="Mock tracking follow-up",
            message="Verify that the dashboard and alerts center show this seeded tracking ticket.",
            status=SupportTicketStatus.OPEN,
        )
        SupportTicket.objects.create(
            owner=users["demo_customer"],
            email=users["demo_customer"].email,
            tracking_number="UPS-MOCK-DONE",
            category=SupportTicketCategory.DELIVERY,
            subject="Mock delivery confirmation",
            message="Use this resolved ticket to test the support history and alert feed.",
            status=SupportTicketStatus.RESOLVED,
        )
        SupportTicket.objects.create(
            owner=users["demo_receiver"],
            email=users["demo_receiver"].email,
            tracking_number="UPS-MOCK-ROUTE",
            category=SupportTicketCategory.ACCOUNT,
            subject="Mock account access review",
            message="Use this in-progress ticket to test cross-page support rendering.",
            status=SupportTicketStatus.IN_PROGRESS,
        )

        SavedQuote.objects.create(
            created_by=users["demo_customer"],
            service_level=QuoteServiceLevel.GROUND,
            origin_x=1,
            origin_y=1,
            destination_x=12,
            destination_y=8,
            package_count=2,
            total_weight_lbs=Decimal("4.50"),
            estimated_cost_cents=1925,
            estimated_business_days=2,
        )
        SavedQuote.objects.create(
            created_by=users["demo_customer"],
            service_level=QuoteServiceLevel.EXPRESS,
            origin_x=2,
            origin_y=4,
            destination_x=18,
            destination_y=11,
            package_count=1,
            total_weight_lbs=Decimal("2.00"),
            estimated_cost_cents=3210,
            estimated_business_days=1,
        )

        self.stdout.write(self.style.SUCCESS("Mock Mini-UPS portal data is ready."))
        self.stdout.write(f"Session: {session.name} (world_id={session.world_id})")
        self.stdout.write("Users:")
        for username, user in users.items():
            self.stdout.write(f"  - {username} / {password} / {user.email}")
        self.stdout.write("Tracking numbers:")
        for shipment in created_shipments:
            self.stdout.write(
                f"  - {shipment.tracking_number} ({shipment.get_status_display()}) owner={shipment.owner_reference or 'public'}"
            )
        self.stdout.write("Support tickets: 3")
        self.stdout.write("Saved quotes: 2")

    def _ensure_user(self, username, email, password):
        user, created = User.objects.get_or_create(username=username, defaults={"email": email})
        if created:
            user.set_password(password)
            user.save()
        else:
            changed = False
            if user.email != email:
                user.email = email
                changed = True
            user.set_password(password)
            changed = True
            if changed:
                user.save()
        return user

    def _ensure_truck(self, session, truck_id, status, current_x, current_y, assignment):
        truck, _ = Truck.objects.update_or_create(
            world_session=session,
            truck_id=truck_id,
            defaults={
                "status": status,
                "current_x": current_x,
                "current_y": current_y,
                "current_assignment": assignment,
            },
        )
        return truck
