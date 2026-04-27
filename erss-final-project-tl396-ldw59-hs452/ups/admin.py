from django.contrib import admin

from .models import Shipment, ShipmentEvent, ShipmentItem, Truck, WorldCommand, WorldSession


class ShipmentItemInline(admin.TabularInline):
    model = ShipmentItem
    extra = 0


class ShipmentEventInline(admin.TabularInline):
    model = ShipmentEvent
    extra = 0
    readonly_fields = ("event_type", "message", "metadata", "created_at")


@admin.register(WorldSession)
class WorldSessionAdmin(admin.ModelAdmin):
    list_display = ("name", "world_id", "host", "port", "is_connected", "next_seq_num")
    search_fields = ("name", "world_id")


@admin.register(Truck)
class TruckAdmin(admin.ModelAdmin):
    list_display = ("truck_id", "world_session", "status", "current_x", "current_y")
    list_filter = ("status",)
    search_fields = ("truck_id",)


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = (
        "tracking_number",
        "package_id",
        "status",
        "owner_reference",
        "assigned_truck",
        "destination_x",
        "destination_y",
        "updated_at",
    )
    list_filter = ("status",)
    search_fields = ("tracking_number", "package_id", "owner_reference", "amazon_order_reference")
    inlines = [ShipmentItemInline, ShipmentEventInline]


@admin.register(WorldCommand)
class WorldCommandAdmin(admin.ModelAdmin):
    list_display = ("seq_num", "command_type", "status", "shipment", "truck", "retry_count")
    list_filter = ("status", "command_type")
    search_fields = ("seq_num", "shipment__tracking_number", "truck__truck_id")

