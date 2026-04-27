from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("ups", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SavedQuote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "service_level",
                    models.CharField(
                        choices=[("ground", "Ground"), ("two_day", "2nd Day"), ("express", "Express")],
                        max_length=32,
                    ),
                ),
                ("origin_x", models.IntegerField()),
                ("origin_y", models.IntegerField()),
                ("destination_x", models.IntegerField()),
                ("destination_y", models.IntegerField()),
                ("package_count", models.PositiveIntegerField(default=1)),
                ("total_weight_lbs", models.DecimalField(decimal_places=2, max_digits=7)),
                ("estimated_cost_cents", models.PositiveIntegerField()),
                ("estimated_business_days", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="saved_quotes", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="SupportTicket",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(max_length=254)),
                ("tracking_number", models.CharField(blank=True, max_length=32)),
                ("subject", models.CharField(max_length=140)),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("tracking", "Tracking"),
                            ("delivery", "Delivery change"),
                            ("account", "Account access"),
                            ("technical", "Technical issue"),
                            ("billing", "Billing / rates"),
                        ],
                        max_length=32,
                    ),
                ),
                ("message", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[("open", "Open"), ("in_progress", "In progress"), ("resolved", "Resolved")],
                        default="open",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="support_tickets", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={"ordering": ("status", "-updated_at")},
        ),
    ]
