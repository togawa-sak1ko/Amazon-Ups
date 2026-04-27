from django.conf import settings
from django.core.management.base import BaseCommand

from ups.models import Truck, TruckStatus, WorldSession


class Command(BaseCommand):
    help = "Create or update the primary world session and seed trucks for UConnect init lists."

    def add_arguments(self, parser):
        parser.add_argument(
            "--session",
            default="primary",
            help="WorldSession.name to create or use (default: primary).",
        )
        parser.add_argument(
            "--trucks",
            type=int,
            default=3,
            help="How many trucks to ensure exist (ids 1..N at origin).",
        )

    def handle(self, *args, **options):
        name = options["session"]
        count = max(0, options["trucks"])

        session, created = WorldSession.objects.get_or_create(
            name=name,
            defaults={
                "host": settings.UPS_WORLD_HOST,
                "port": settings.UPS_WORLD_PORT,
            },
        )
        action = "Created" if created else "Using existing"
        self.stdout.write(f"{action} WorldSession name={name!r} host={session.host!r} port={session.port}.")

        for truck_id in range(1, count + 1):
            truck, t_created = Truck.objects.get_or_create(
                world_session=session,
                truck_id=truck_id,
                defaults={
                    "status": TruckStatus.IDLE,
                    "current_x": 0,
                    "current_y": 0,
                },
            )
            tag = "created" if t_created else "already present"
            self.stdout.write(f"  Truck id={truck.truck_id} ({tag}) at ({truck.current_x}, {truck.current_y}).")
