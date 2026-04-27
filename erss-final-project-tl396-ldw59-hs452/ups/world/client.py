import socket

from django.utils import timezone

from ups.models import Shipment, ShipmentStatus, TruckStatus, WorldCommand, WorldCommandStatus, WorldSession
from ups.services import (
    acknowledge_world_command,
    mark_shipment_delivered,
    mark_shipment_waiting,
    record_world_command_error,
    sync_truck_state,
)

from .protocol import read_delimited_message, send_delimited_message


class WorldSocketClient:
    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket = None

    def open(self):
        if self._socket is None:
            self._socket = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self._socket.settimeout(self.timeout)
        return self._socket

    def close(self):
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def require_proto_bindings(self):
        try:
            from ups.world.generated import world_ups_pb2
        except ImportError as exc:
            raise RuntimeError(
                "Generated protobuf bindings are missing. Run protoc against proto/world_ups.proto "
                "and place the output under ups/world/generated/ before enabling live world traffic."
            ) from exc
        return world_ups_pb2

    def build_connect_message(self, world_id=None, trucks=None):
        pb2 = self.require_proto_bindings()
        message = pb2.UConnect(isAmazon=False)
        if world_id is not None:
            message.worldid = world_id
        for truck in trucks or []:
            init_truck = message.trucks.add()
            init_truck.id = truck["id"]
            init_truck.x = truck.get("x", 0)
            init_truck.y = truck.get("y", 0)
        return message

    def connect_world(self, world_id=None, trucks=None):
        """Handshake: send UConnect, read UConnected. Spec requires result string 'connected!'."""
        uconnect = self.build_connect_message(world_id=world_id, trucks=trucks)
        pb2 = self.require_proto_bindings()
        self.send(uconnect)
        # Simulator replies with UConnected before any UCommands/UResponses traffic.
        return self.receive(pb2.UConnected)

    def send(self, message):
        sock = self.open()
        send_delimited_message(sock, message)

    def receive(self, message_cls):
        sock = self.open()
        payload = read_delimited_message(sock)
        message = message_cls()
        message.ParseFromString(payload)
        return message

    def build_pickup_command(self, pb2, command: WorldCommand):
        """Build a world pickup command from a queued UPS command.

        Args:
            pb2: Generated protobuf module containing `UCommands` definitions.
            command (WorldCommand): Command whose payload must include `truck_id` and `warehouse_id`.

        Raises:
            ValueError: If required pickup fields are missing from `command.payload`.

        Returns:
            pb2.UCommands: A message with one populated pickup command entry.
        """
        payload = command.payload or {}
        
        # Check if any fields are missing from the payload
        required = ("truck_id", "warehouse_id")
        missing = [field for field in required if field not in payload]
        if missing:
            missing_fields = ", ".join(missing)
            raise ValueError(f"pickup command {command.seq_num} missing fields: {missing_fields}")

        # Parse the message
        message = pb2.UCommands()
        pickup = message.pickups.add()
        pickup.truckid = int(payload["truck_id"])
        pickup.whid = int(payload["warehouse_id"])
        pickup.seqnum = int(command.seq_num)
        return message

    def build_delivery_command(self, pb2, command: WorldCommand):
        payload = command.payload or {}
        
        # Ensure the shared delivery metadata is present
        if "truck_id" not in payload:
            raise ValueError(f"deliver command {command.seq_num} missing field: truck_id")

        # Prefer batched package destinations when provided
        destinations = payload.get("packages")
        if not destinations:
            # Fall back to the single-destination payload format
            required = ("package_id", "destination_x", "destination_y")
            missing = [field for field in required if field not in payload]
            if missing:
                missing_fields = ", ".join(missing)
                raise ValueError(f"deliver command {command.seq_num} missing fields: {missing_fields}")
            destinations = [
                {
                    "package_id": payload["package_id"],
                    "x": payload["destination_x"],
                    "y": payload["destination_y"],
                }
            ]

        # Parse the message
        message = pb2.UCommands()
        delivery = message.deliveries.add()
        delivery.truckid = int(payload["truck_id"])
        delivery.seqnum = int(command.seq_num)
        for destination in destinations:
            dropoff = delivery.packages.add()
            dropoff.packageid = int(destination["package_id"])
            dropoff.x = int(destination["x"])
            dropoff.y = int(destination["y"])
        return message

    def build_query_command(self, pb2, command: WorldCommand):
        payload = command.payload or {}
        
        # Ensure query command includes the target truck id
        if "truck_id" not in payload:
            raise ValueError(f"query command {command.seq_num} missing field: truck_id")

        # Parse the message
        message = pb2.UCommands()
        query = message.queries.add()
        query.truckid = int(payload["truck_id"])
        query.seqnum = int(command.seq_num)
        return message

    def dispatch(self, command: WorldCommand):
        # Load generated protobuf classes for world messages
        pb2 = self.require_proto_bindings()

        # Normalize command type and map aliases to builders
        command_type = (command.command_type or "").strip().lower()
        builders = {
            "pickup": self.build_pickup_command,
            "pickups": self.build_pickup_command,
            "deliver": self.build_delivery_command,
            "delivery": self.build_delivery_command,
            "deliveries": self.build_delivery_command,
            "query": self.build_query_command,
            "queries": self.build_query_command,
        }
        
        # Reject unsupported command names before sending
        builder = builders.get(command_type)
        if builder is None:
            raise ValueError(f"Unsupported world command type: {command.command_type}")

        # Build, transmit, and persist status transition
        world_message = builder(pb2, command)
        self.send(world_message)
        self.mark_sent(command)
        return world_message

    def mark_sent(self, command: WorldCommand):
        command.status = WorldCommandStatus.SENT
        command.sent_at = timezone.now()
        command.save(update_fields=["status", "sent_at", "updated_at"])

    def map_world_truck_status(self, world_status: str) -> str:
        normalized = (world_status or "").strip().lower()
        # World status strings do not exactly match our enum labels.
        mapping = {
            "idle": TruckStatus.IDLE,
            "traveling": TruckStatus.TRAVELING,
            "arrive warehouse": TruckStatus.ARRIVED_WAREHOUSE,
            "arrived warehouse": TruckStatus.ARRIVED_WAREHOUSE,
            "loading": TruckStatus.LOADING,
            "delivering": TruckStatus.DELIVERING,
        }
        return mapping.get(normalized, TruckStatus.IDLE)

    def acknowledge_inbound(self, pb2, ack_numbers):
        if not ack_numbers:
            return

        message = pb2.UCommands()
        # Deduplicate so world sees one ack per response seqnum. (idempotency from lecture)
        message.acks.extend(sorted(set(int(number) for number in ack_numbers)))
        self.send(message)

    def handle_command_acks(self, world_session: WorldSession, ack_numbers):
        if not ack_numbers:
            return 0

        acked_count = 0
        for command in WorldCommand.objects.filter(
            world_session=world_session,
            seq_num__in=[int(number) for number in ack_numbers],
        ):
            if command.status == WorldCommandStatus.ACKED:
                continue
            # Marking acked here enables retry logic to skip already accepted commands.
            acknowledge_world_command(command)
            acked_count += 1
        return acked_count

    def handle_completion(self, world_session: WorldSession, completion, notify_amazon=True):
        # Completions carry the truck's latest location and lifecycle status.
        truck = sync_truck_state(
            world_session=world_session,
            truck_id=int(completion.truckid),
            status=self.map_world_truck_status(completion.status),
            current_x=int(completion.x),
            current_y=int(completion.y),
        )
        # Match completion.seqnum back to the command that produced this event.
        command = WorldCommand.objects.select_related("shipment").filter(
            world_session=world_session,
            seq_num=int(completion.seqnum),
        ).first()
        if command is not None:
            # Persist completion timestamp for auditing and debugging.
            command.completed_at = timezone.now()
            command.save(update_fields=["completed_at", "updated_at"])
            if command.shipment is not None and command.command_type in {"pickup", "pickups"}:
                # Pickup completion means truck reached warehouse and can be loaded.
                mark_shipment_waiting(command.shipment, truck, notify_amazon=notify_amazon)

    def handle_delivered(self, delivery_made, notify_amazon=True):
        # Delivery events are keyed by package id, so resolve shipment that way.
        shipment = Shipment.objects.select_related("assigned_truck").filter(
            package_id=int(delivery_made.packageid)
        ).first()
        if shipment is None:
            # Ignore deliveries for unknown package ids instead of crashing daemon loop.
            return
        if shipment.status != ShipmentStatus.DELIVERED:
            # This guard keeps delivery handling idempotent across duplicate world messages.
            mark_shipment_delivered(shipment, notify_amazon=notify_amazon)
        WorldCommand.objects.filter(
            shipment=shipment,
            command_type__in=["deliver", "delivery", "deliveries"],
            completed_at__isnull=True,
        ).update(completed_at=timezone.now())

    def handle_truck_status(self, world_session: WorldSession, truck_status, notify_amazon=True):
        # Truck status updates are periodic snapshots from world, not command completions.
        mapped_status = self.map_world_truck_status(truck_status.status)
        truck = sync_truck_state(
            world_session=world_session,
            truck_id=int(truck_status.truckid),
            status=mapped_status,
            current_x=int(truck_status.x),
            current_y=int(truck_status.y),
        )
        if mapped_status == TruckStatus.ARRIVED_WAREHOUSE:
            # Some simulator builds omit pickup completions but do emit truckstatus updates.
            # Promote the corresponding acked pickup command to completed so Amazon receives
            # truck-arrived callback and can continue the load/deliver chain.
            pending_pickup = (
                WorldCommand.objects.select_related("shipment")
                .filter(
                    world_session=world_session,
                    truck=truck,
                    status=WorldCommandStatus.ACKED,
                    command_type__in=["pickup", "pickups"],
                    completed_at__isnull=True,
                )
                .order_by("created_at")
                .first()
            )
            if pending_pickup is not None and pending_pickup.shipment is not None:
                pending_pickup.completed_at = timezone.now()
                pending_pickup.save(update_fields=["completed_at", "updated_at"])
                mark_shipment_waiting(pending_pickup.shipment, truck, notify_amazon=notify_amazon)

    def handle_error(self, world_session: WorldSession, world_error):
        # originseqnum points to the command world rejected.
        command = WorldCommand.objects.filter(
            world_session=world_session,
            seq_num=int(world_error.originseqnum),
        ).first()
        if command is None:
            return
        # May requeue as PENDING until UPS_WORLD_COMMAND_MAX_RETRIES is exceeded.
        record_world_command_error(command, world_error.err)

    def process_world_response(self, world_session: WorldSession, response, notify_amazon=True):
        pb2 = self.require_proto_bindings()
        inbound_acks = []
        # `finished` becomes true when world closes after handling a disconnect request.
        finished = bool(getattr(response, "finished", False))

        # These acks are for commands we previously sent to world.
        acked_commands = self.handle_command_acks(world_session, getattr(response, "acks", []))

        # Completion responses mean a truck finished a pickup or delivery batch action.
        completions = list(getattr(response, "completions", []))
        for completion in completions:
            self.handle_completion(world_session, completion, notify_amazon=notify_amazon)
            # Ack each response seqnum so world can drop this completion notification.
            inbound_acks.append(int(completion.seqnum))

        # Delivered responses are per-package delivery confirmations.
        delivered = list(getattr(response, "delivered", []))
        for delivered_notice in delivered:
            self.handle_delivered(delivered_notice, notify_amazon=notify_amazon)
            # Ack each response seqnum so world can drop this delivery notification.
            inbound_acks.append(int(delivered_notice.seqnum))

        # Truckstatus responses provide latest truck position/state snapshots.
        truck_statuses = list(getattr(response, "truckstatus", []))
        for truck_status in truck_statuses:
            self.handle_truck_status(world_session, truck_status, notify_amazon=notify_amazon)
            # Ack each response seqnum so world can drop this status update.
            inbound_acks.append(int(truck_status.seqnum))

        # Error responses indicate world rejected a previously sent command.
        errors = list(getattr(response, "error", []))
        for world_error in errors:
            self.handle_error(world_session, world_error)
            # Ack each response seqnum so world can stop retrying this error message.
            inbound_acks.append(int(world_error.seqnum))

        # Ack response seqnums so world can stop resending these notifications.
        self.acknowledge_inbound(pb2, inbound_acks)

        return {
            "acked_commands": acked_commands,
            "completions": len(completions),
            "delivered": len(delivered),
            "truckstatus": len(truck_statuses),
            "errors": len(errors),
            "inbound_acks_sent": len(set(inbound_acks)),
            "finished": finished,
        }
