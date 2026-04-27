from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorldSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(default="primary", max_length=64, unique=True)),
                ("world_id", models.BigIntegerField(blank=True, null=True, unique=True)),
                ("host", models.CharField(default="world", max_length=255)),
                ("port", models.PositiveIntegerField(default=12345)),
                ("is_connected", models.BooleanField(default=False)),
                ("next_seq_num", models.PositiveBigIntegerField(default=1)),
                ("last_heartbeat_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="Truck",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("truck_id", models.PositiveIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("idle", "Idle"),
                            ("traveling", "Traveling to warehouse"),
                            ("arrived_warehouse", "Arrived at warehouse"),
                            ("loading", "Loading"),
                            ("delivering", "Delivering"),
                        ],
                        default="idle",
                        max_length=32,
                    ),
                ),
                ("current_x", models.IntegerField(default=0)),
                ("current_y", models.IntegerField(default=0)),
                ("current_assignment", models.CharField(blank=True, max_length=128)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "world_session",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="trucks", to="ups.worldsession"),
                ),
            ],
            options={
                "ordering": ("truck_id",),
                "unique_together": {("world_session", "truck_id")},
            },
        ),
        migrations.CreateModel(
            name="Shipment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("package_id", models.PositiveBigIntegerField(unique=True)),
                ("tracking_number", models.CharField(max_length=32, unique=True)),
                ("owner_reference", models.CharField(blank=True, max_length=150)),
                ("warehouse_id", models.IntegerField()),
                ("origin_x", models.IntegerField(default=0)),
                ("origin_y", models.IntegerField(default=0)),
                ("destination_x", models.IntegerField()),
                ("destination_y", models.IntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("created", "Created"),
                            ("truck_en_route_to_warehouse", "Truck en route to warehouse"),
                            ("truck_waiting_for_package", "Truck waiting for package"),
                            ("loading", "Loading"),
                            ("loaded", "Loaded"),
                            ("out_for_delivery", "Out for delivery"),
                            ("delivered", "Delivered"),
                            ("error", "Exception"),
                        ],
                        default="created",
                        max_length=48,
                    ),
                ),
                ("last_known_world_status", models.CharField(blank=True, max_length=64)),
                ("amazon_order_reference", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                (
                    "assigned_truck",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="shipments", to="ups.truck"),
                ),
                (
                    "owner",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="shipments", to=settings.AUTH_USER_MODEL),
                ),
                (
                    "world_session",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="shipments", to="ups.worldsession"),
                ),
            ],
            options={
                "ordering": ("-updated_at",),
            },
        ),
        migrations.CreateModel(
            name="ShipmentEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(max_length=64)),
                ("message", models.TextField()),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "shipment",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="ups.shipment"),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="ShipmentItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sku", models.CharField(blank=True, max_length=64)),
                ("description", models.CharField(max_length=255)),
                ("quantity", models.PositiveIntegerField(default=1)),
                (
                    "shipment",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="ups.shipment"),
                ),
            ],
            options={
                "ordering": ("id",),
            },
        ),
        migrations.CreateModel(
            name="WorldCommand",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("seq_num", models.PositiveBigIntegerField()),
                ("command_type", models.CharField(max_length=64)),
                ("payload", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("sent", "Sent"),
                            ("acked", "Acked"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("acked_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("retry_count", models.PositiveIntegerField(default=0)),
                ("last_error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "shipment",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="world_commands", to="ups.shipment"),
                ),
                (
                    "truck",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="world_commands", to="ups.truck"),
                ),
                (
                    "world_session",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="commands", to="ups.worldsession"),
                ),
            ],
            options={
                "ordering": ("status", "created_at"),
                "unique_together": {("world_session", "seq_num")},
            },
        ),
    ]

