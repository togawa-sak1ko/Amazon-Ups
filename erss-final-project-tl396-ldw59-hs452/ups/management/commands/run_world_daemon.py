import os
import time
from datetime import timedelta

from google.protobuf.message import DecodeError
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from ups.models import Shipment, ShipmentStatus, WorldCommand, WorldCommandStatus, WorldSession
from ups.services import (
    notify_amazon_truck_arrived_for_waiting_shipment,
    queue_world_command,
    record_world_command_error,
)
from ups.world.client import WorldSocketClient


class Command(BaseCommand):
    help = "Poll queued world commands and hand them to the UPS world client."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._live_client = None
        self._live_endpoint = None

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one polling cycle and exit.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Inspect queued commands without sending them to the world server.",
        )
        parser.add_argument(
            "--poll-interval",
            type=int,
            default=5,
            help="Seconds to sleep between polling cycles.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"] or settings.UPS_WORLD_DAEMON_DRY_RUN
        once = options["once"]
        poll_interval = options["poll_interval"]

        while True:
            # Update the world session heartbeat on every poll cycle
            self._heartbeat()

            # Either inspect queued commands or actively dispatch them
            if dry_run:
                self._inspect_queue()
            else:
                self._process_queue()

            # Allow one-shot execution for local debugging/cron usage
            if once:
                break

            time.sleep(poll_interval)

    def _heartbeat(self):
        session, _ = WorldSession.objects.get_or_create(
            name="primary",
            defaults={"host": settings.UPS_WORLD_HOST, "port": settings.UPS_WORLD_PORT},
        )
        session.last_heartbeat_at = timezone.now()
        session.save(update_fields=["last_heartbeat_at"])

    def _reset_live_client(self):
        if self._live_client is not None:
            self._live_client.close()
        self._live_client = None
        self._live_endpoint = None

    def _get_or_create_client(self, host: str, port: int) -> WorldSocketClient:
        endpoint = (host, port)
        if self._live_client is not None and self._live_endpoint == endpoint:
            return self._live_client
        self._reset_live_client()
        self._live_client = WorldSocketClient(host=host, port=port)
        self._live_endpoint = endpoint
        return self._live_client

    def _inspect_queue(self):
        pending = WorldCommand.objects.filter(status=WorldCommandStatus.PENDING).select_related(
            "shipment", "truck"
        )
        if not pending.exists():
            self.stdout.write("No pending world commands.")
            return

        for command in pending[:20]:
            self.stdout.write(
                f"[dry-run] seq={command.seq_num} type={command.command_type} "
                f"shipment={command.shipment_id or '-'} truck={command.truck_id or '-'}"
            )

    def _retry_waiting_pickup_callbacks(self):
        waiting_shipments = (
            Shipment.objects.filter(
                status=ShipmentStatus.WAITING_FOR_PICKUP,
                assigned_truck__isnull=False,
            )
            .select_related("assigned_truck")
            .order_by("created_at")[:20]
        )
        for shipment in waiting_shipments:
            if shipment.events.filter(event_type="amazon_truck_arrived_notified").exists():
                continue
            failure_count = shipment.events.filter(event_type="amazon_callback_failed").count()
            if failure_count >= 5:
                continue
            if notify_amazon_truck_arrived_for_waiting_shipment(shipment):
                self.stdout.write(f"Retried Amazon truck-arrived callback for package {shipment.package_id}.")

    def _connect_session_to_world(self, client: WorldSocketClient, session: WorldSession):
        """Send UConnect and persist world id when the simulator accepts the session."""
        init_trucks = [
            {"id": truck.truck_id, "x": truck.current_x, "y": truck.current_y}
            for truck in session.trucks.order_by("truck_id")
        ]
        world_id = session.world_id
        # Always try to register trucks first, even when reconnecting to an existing world id.
        # If trucks already exist, simulator duplicate errors are handled below by retrying
        # the same world_id with trucks=None.
        trucks = init_trucks or None
        connected = client.connect_world(world_id=world_id, trucks=trucks)
        if connected.result != "connected!":
            lowered = connected.result.lower()
            if world_id is not None:
                duplicate_markers = ("already exists", "duplicate")
                stale_world_markers = ("world with world_id", "not available")
                if any(marker in lowered for marker in duplicate_markers):
                    connected = client.connect_world(world_id=world_id, trucks=None)
                elif all(marker in lowered for marker in stale_world_markers):
                    # World session expired/restarted on simulator side; re-register fresh world.
                    session.world_id = None
                    session.is_connected = False
                    session.save(update_fields=["world_id", "is_connected", "updated_at"])
                    connected = client.connect_world(world_id=None, trucks=init_trucks or None)
        if connected.result != "connected!":
            raise ValueError(connected.result)
        session.world_id = int(connected.worldid)
        session.is_connected = True
        session.save(update_fields=["world_id", "is_connected", "updated_at"])
        self.stdout.write(f"Connected to world id={session.world_id}.")

    def _process_queue(self):
        session, _ = WorldSession.objects.get_or_create(
            name="primary",
            defaults={"host": settings.UPS_WORLD_HOST, "port": settings.UPS_WORLD_PORT},
        )
        self._retry_waiting_pickup_callbacks()
        # If pickups are acked but never completed, actively query truck state to coax
        # simulator updates on implementations that do not push completions promptly.
        acked_pickups = (
            WorldCommand.objects.filter(
                world_session=session,
                status=WorldCommandStatus.ACKED,
                command_type__in=["pickup", "pickups"],
                completed_at__isnull=True,
                truck__isnull=False,
            )
            .select_related("truck")
            .order_by("created_at")
        )
        for command in acked_pickups:
            existing_query_in_flight = WorldCommand.objects.filter(
                world_session=session,
                command_type__in=["query", "queries"],
                truck=command.truck,
                status__in=[WorldCommandStatus.PENDING, WorldCommandStatus.SENT],
            ).exists()
            if not existing_query_in_flight:
                queue_world_command(
                    world_session=session,
                    command_type="query",
                    payload={"truck_id": command.truck.truck_id},
                    shipment=command.shipment,
                    truck=command.truck,
                )

        # If delivery commands are acked but no delivery completion arrives for a while,
        # enqueue a fresh deliver command to recover from dropped completion notifications.
        deliver_stale_cutoff = timezone.now() - timedelta(seconds=30)
        stale_delivers = (
            WorldCommand.objects.filter(
                world_session=session,
                status=WorldCommandStatus.ACKED,
                command_type__in=["deliver", "delivery", "deliveries"],
                completed_at__isnull=True,
                acked_at__lt=deliver_stale_cutoff,
                shipment__isnull=False,
                truck__isnull=False,
            )
            .exclude(shipment__status=ShipmentStatus.DELIVERED)
            .select_related("shipment", "truck")
            .order_by("acked_at")
        )
        for command in stale_delivers:
            shipment = command.shipment
            existing_deliver_in_flight = WorldCommand.objects.filter(
                world_session=session,
                shipment=shipment,
                command_type__in=["deliver", "delivery", "deliveries"],
                status__in=[WorldCommandStatus.PENDING, WorldCommandStatus.SENT],
            ).exists()
            if existing_deliver_in_flight:
                continue
            queue_world_command(
                world_session=session,
                command_type="deliver",
                payload={
                    "truck_id": command.truck.truck_id,
                    "package_id": shipment.package_id,
                    "destination_x": shipment.destination_x,
                    "destination_y": shipment.destination_y,
                },
                shipment=shipment,
                truck=command.truck,
            )

        # Requeue SENT commands that likely got lost after a dropped world socket.
        stale_cutoff = timezone.now() - timedelta(seconds=15)
        stale_sent = WorldCommand.objects.filter(
            world_session=session,
            status=WorldCommandStatus.SENT,
            sent_at__lt=stale_cutoff,
        ).order_by("sent_at")
        stale_count = 0
        for command in stale_sent:
            will_retry = record_world_command_error(command, "stale sent command from dropped world connection")
            if will_retry:
                stale_count += 1
        if stale_count:
            self.stdout.write(f"Requeued {stale_count} stale sent command(s).")

        # Fetch a small FIFO batch to avoid unbounded send loops
        pending = list(
            WorldCommand.objects.filter(status=WorldCommandStatus.PENDING, world_session=session)
            .select_related("shipment", "truck")
            .order_by("created_at")[:20]
        )
        in_flight_exists = WorldCommand.objects.filter(
            world_session=session,
            status=WorldCommandStatus.SENT,
        ).exists()
        awaiting_completion_exists = WorldCommand.objects.filter(
            world_session=session,
            status=WorldCommandStatus.ACKED,
            completed_at__isnull=True,
        ).exists()
        if not pending and not in_flight_exists and not awaiting_completion_exists:
            self.stdout.write("No pending world commands.")
            return
        if not pending and (in_flight_exists or awaiting_completion_exists):
            self.stdout.write("No pending commands; polling world for in-flight/acked completions.")

        # Prefer explicit env overrides for this daemon process, then DB session endpoint.
        endpoint_host = os.environ.get("WORLD_HOST") or session.host or settings.UPS_WORLD_HOST
        endpoint_port = int(os.environ.get("WORLD_PORT") or session.port or settings.UPS_WORLD_PORT)
        if endpoint_host != session.host or endpoint_port != session.port:
            session.host = endpoint_host
            session.port = endpoint_port
            session.save(update_fields=["host", "port", "updated_at"])

        client = self._get_or_create_client(host=endpoint_host, port=endpoint_port)
        # DB connectivity flag can outlive process restarts; require handshake whenever
        # this daemon has no active in-memory socket yet.
        needs_handshake = (not session.is_connected) or (self._live_client is None)
        if needs_handshake:
            try:
                self._connect_session_to_world(client, session)
            except (RuntimeError, ValueError, OSError) as exc:
                self.stderr.write(f"World UConnect failed: {exc}")
                session.is_connected = False
                session.save(update_fields=["is_connected", "updated_at"])
                self._reset_live_client()
                return

        # Reuse one socket client for the current cycle (already connected).
        for command in pending:
            try:
                client.dispatch(command)
            except (RuntimeError, ValueError) as exc:
                # Record local dispatch failures under the same retry budget as world UErr.
                will_retry = record_world_command_error(command, str(exc))
                retry_note = "requeued for retry" if will_retry else "marked failed"
                # Stop the cycle so we can surface and address the first failure.
                self.stderr.write(f"{exc} ({retry_note})")
                if "Socket closed" in str(exc):
                    session.is_connected = False
                    session.save(update_fields=["is_connected", "updated_at"])
                    self._reset_live_client()
                return
        # Process any world acknowledgements/completions after dispatching
        self._consume_world_responses(client, session)

    def _consume_world_responses(self, client: WorldSocketClient, session: WorldSession):
        pb2 = client.require_proto_bindings()
        # Read a bounded number of responses per cycle to keep polling responsive
        for i in range(5):
            try:
                response = client.receive(pb2.UResponses)
            except TimeoutError:
                # No more responses available right now
                return
            except DecodeError as exc:
                self.stderr.write(f"World response decode failed: {exc}")
                session.is_connected = False
                session.save(update_fields=["is_connected", "updated_at"])
                self._reset_live_client()
                return
            except OSError as exc:
                self.stderr.write(f"World response read failed: {exc}")
                session.is_connected = False
                session.save(update_fields=["is_connected", "updated_at"])
                self._reset_live_client()
                return

            # Persist acknowledgements/truck updates from each response
            summary = client.process_world_response(session, response)
            self.stdout.write(
                "Processed world response "
                f"(acks={summary['acked_commands']}, completions={summary['completions']}, "
                f"delivered={summary['delivered']}, truckstatus={summary['truckstatus']}, "
                f"errors={summary['errors']})."
            )
            if summary.get("finished"):
                # Simulator indicated it is done and will close the current socket.
                session.is_connected = False
                session.save(update_fields=["is_connected", "updated_at"])
                client.close()
                self.stdout.write("World connection reported finished=true; marked session disconnected.")
                return
