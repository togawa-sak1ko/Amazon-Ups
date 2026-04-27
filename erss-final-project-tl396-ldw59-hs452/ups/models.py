from django.contrib.auth import get_user_model
from django.db import models


User = get_user_model()


class ShipmentStatus(models.TextChoices):
    CREATED = "created", "Created"
    EN_ROUTE_TO_WAREHOUSE = "truck_en_route_to_warehouse", "Truck en route to warehouse"
    WAITING_FOR_PICKUP = "truck_waiting_for_package", "Truck waiting for package"
    LOADING = "loading", "Loading"
    LOADED = "loaded", "Loaded"
    OUT_FOR_DELIVERY = "out_for_delivery", "Out for delivery"
    DELIVERED = "delivered", "Delivered"
    ERROR = "error", "Exception"


class TruckStatus(models.TextChoices):
    IDLE = "idle", "Idle"
    TRAVELING = "traveling", "Traveling to warehouse"
    ARRIVED_WAREHOUSE = "arrived_warehouse", "Arrived at warehouse"
    LOADING = "loading", "Loading"
    DELIVERING = "delivering", "Delivering"


class WorldCommandStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    ACKED = "acked", "Acked"
    FAILED = "failed", "Failed"


class QuoteServiceLevel(models.TextChoices):
    GROUND = "ground", "Ground"
    TWO_DAY = "two_day", "2nd Day"
    EXPRESS = "express", "Express"


class SupportTicketStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In progress"
    RESOLVED = "resolved", "Resolved"


class SupportTicketCategory(models.TextChoices):
    TRACKING = "tracking", "Tracking"
    DELIVERY = "delivery", "Delivery change"
    ACCOUNT = "account", "Account access"
    TECHNICAL = "technical", "Technical issue"
    BILLING = "billing", "Billing / rates"


class WorldSession(models.Model):
    name = models.CharField(max_length=64, unique=True, default="primary")
    world_id = models.BigIntegerField(null=True, blank=True, unique=True)
    host = models.CharField(max_length=255, default="world")
    port = models.PositiveIntegerField(default=12345)
    is_connected = models.BooleanField(default=False)
    next_seq_num = models.PositiveBigIntegerField(default=1)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name


class Truck(models.Model):
    world_session = models.ForeignKey(WorldSession, related_name="trucks", on_delete=models.CASCADE)
    truck_id = models.PositiveIntegerField()
    status = models.CharField(max_length=32, choices=TruckStatus.choices, default=TruckStatus.IDLE)
    current_x = models.IntegerField(default=0)
    current_y = models.IntegerField(default=0)
    current_assignment = models.CharField(max_length=128, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("truck_id",)
        unique_together = ("world_session", "truck_id")

    def __str__(self) -> str:
        return f"Truck {self.truck_id}"


class Shipment(models.Model):
    world_session = models.ForeignKey(
        WorldSession,
        related_name="shipments",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    package_id = models.PositiveBigIntegerField(unique=True)
    tracking_number = models.CharField(max_length=32, unique=True)
    owner = models.ForeignKey(
        User,
        related_name="shipments",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    owner_reference = models.CharField(max_length=150, blank=True)
    warehouse_id = models.IntegerField()
    origin_x = models.IntegerField(default=0)
    origin_y = models.IntegerField(default=0)
    destination_x = models.IntegerField()
    destination_y = models.IntegerField()
    assigned_truck = models.ForeignKey(
        Truck,
        related_name="shipments",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=48, choices=ShipmentStatus.choices, default=ShipmentStatus.CREATED)
    last_known_world_status = models.CharField(max_length=64, blank=True)
    amazon_order_reference = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-updated_at",)

    def __str__(self) -> str:
        return self.tracking_number

    def can_redirect(self) -> bool:
        return self.status in {
            ShipmentStatus.CREATED,
            ShipmentStatus.EN_ROUTE_TO_WAREHOUSE,
            ShipmentStatus.WAITING_FOR_PICKUP,
            ShipmentStatus.LOADING,
            ShipmentStatus.LOADED,
        }

    def assign_owner_from_reference(self):
        if not self.owner_reference:
            return
        matched_user = User.objects.filter(username__iexact=self.owner_reference).first()
        if matched_user:
            self.owner = matched_user

    def as_tracking_dict(self) -> dict:
        return {
            "tracking_number": self.tracking_number,
            "package_id": self.package_id,
            "status": self.status,
            "status_label": self.get_status_display(),
            "warehouse_id": self.warehouse_id,
            "destination": {"x": self.destination_x, "y": self.destination_y},
            "owner_reference": self.owner_reference,
            "assigned_truck": self.assigned_truck.truck_id if self.assigned_truck else None,
            "items": [
                {"sku": item.sku, "description": item.description, "quantity": item.quantity}
                for item in self.items.all()
            ],
            "events": [
                {
                    "type": event.event_type,
                    "message": event.message,
                    "created_at": event.created_at.isoformat(),
                }
                for event in self.events.all()[:10]
            ],
        }


class ShipmentItem(models.Model):
    shipment = models.ForeignKey(Shipment, related_name="items", on_delete=models.CASCADE)
    sku = models.CharField(max_length=64, blank=True)
    description = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ("id",)

    def __str__(self) -> str:
        return f"{self.description} x{self.quantity}"


class ShipmentEvent(models.Model):
    shipment = models.ForeignKey(Shipment, related_name="events", on_delete=models.CASCADE)
    event_type = models.CharField(max_length=64)
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class WorldCommand(models.Model):
    world_session = models.ForeignKey(WorldSession, related_name="commands", on_delete=models.CASCADE)
    shipment = models.ForeignKey(
        Shipment,
        related_name="world_commands",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    truck = models.ForeignKey(
        Truck,
        related_name="world_commands",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    seq_num = models.PositiveBigIntegerField()
    command_type = models.CharField(max_length=64)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=WorldCommandStatus.choices,
        default=WorldCommandStatus.PENDING,
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    acked_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("status", "created_at")
        unique_together = ("world_session", "seq_num")

    def __str__(self) -> str:
        return f"{self.command_type}#{self.seq_num}"


class SavedQuote(models.Model):
    created_by = models.ForeignKey(
        User,
        related_name="saved_quotes",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    service_level = models.CharField(max_length=32, choices=QuoteServiceLevel.choices)
    origin_x = models.IntegerField()
    origin_y = models.IntegerField()
    destination_x = models.IntegerField()
    destination_y = models.IntegerField()
    package_count = models.PositiveIntegerField(default=1)
    total_weight_lbs = models.DecimalField(max_digits=7, decimal_places=2)
    estimated_cost_cents = models.PositiveIntegerField()
    estimated_business_days = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.get_service_level_display()} quote"

    @property
    def estimated_cost_display(self) -> str:
        return f"${self.estimated_cost_cents / 100:.2f}"


class SupportTicket(models.Model):
    owner = models.ForeignKey(
        User,
        related_name="support_tickets",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    email = models.EmailField()
    tracking_number = models.CharField(max_length=32, blank=True)
    subject = models.CharField(max_length=140)
    category = models.CharField(max_length=32, choices=SupportTicketCategory.choices)
    message = models.TextField()
    status = models.CharField(
        max_length=16,
        choices=SupportTicketStatus.choices,
        default=SupportTicketStatus.OPEN,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("status", "-updated_at")

    def __str__(self) -> str:
        return self.subject
