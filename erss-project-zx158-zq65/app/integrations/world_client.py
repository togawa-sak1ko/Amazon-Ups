from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from typing import Optional, Type

from google.protobuf.message import Message
from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations.generated import world_amazon_pb2
from app.services.order_service import mark_failure, mark_inventory_arrived, mark_loaded, mark_packed
from app.services.runtime_state_service import get_runtime_int, set_runtime_int


def _encode_varint(value: int) -> bytes:
    chunks: list[int] = []
    while True:
        to_write = value & 0x7F
        value >>= 7
        if value:
            chunks.append(to_write | 0x80)
        else:
            chunks.append(to_write)
            return bytes(chunks)


def _read_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("World server closed the connection")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_varint(sock: socket.socket) -> int:
    shift = 0
    value = 0
    while True:
        raw = sock.recv(1)
        if not raw:
            raise ConnectionError("World server closed the connection")
        byte = raw[0]
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value
        shift += 7


@dataclass(slots=True)
class PendingWorldCommand:
    key: str
    seqnum: int
    package_id: int
    kind: str
    request: Message
    acked: bool = False
    completed: bool = False
    last_sent_at: float = 0.0


class WorldClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._socket: Optional[socket.socket] = None
        self._world_id = self.settings.world_id
        self._next_seqnum = 1
        self._commands_by_key: dict[str, PendingWorldCommand] = {}
        self._commands_by_seq: dict[int, PendingWorldCommand] = {}
        self._pending_response_acks: set[int] = set()
        self._retry_interval = 1.0

    @property
    def connected(self) -> bool:
        return self._socket is not None

    def _send_message(self, message: Message) -> None:
        if self._socket is None:
            raise ConnectionError("World client is not connected")
        payload = message.SerializeToString()
        self._socket.sendall(_encode_varint(len(payload)) + payload)

    def _recv_message(self, message_cls: Type[Message], timeout: float) -> Optional[Message]:
        if self._socket is None:
            return None
        self._socket.settimeout(timeout)
        try:
            size = _read_varint(self._socket)
            payload = _read_exact(self._socket, size)
        except socket.timeout:
            return None
        finally:
            self._socket.settimeout(None)
        message = message_cls()
        message.ParseFromString(payload)
        return message

    def connect(self, db: Session) -> None:
        if self.connected:
            return
        if self._world_id is None:
            self._world_id = get_runtime_int(db, "world_id")
        sock = socket.create_connection((self.settings.world_host, self.settings.world_port), timeout=5.0)
        self._socket = sock

        connect = world_amazon_pb2.AConnect(isAmazon=True)
        if self._world_id is not None:
            connect.worldid = self._world_id
        connect.initwh.add(id=self.settings.warehouse_id, x=self.settings.warehouse_x, y=self.settings.warehouse_y)
        self._send_message(connect)

        response = self._recv_message(world_amazon_pb2.AConnected, timeout=5.0)
        if response is None or response.result != "connected!":
            self.close()
            result = "no response" if response is None else response.result
            raise ConnectionError(f"Failed to connect to world: {result}")
        self._world_id = response.worldid
        set_runtime_int(db, "world_id", int(response.worldid))
        db.commit()

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None

    def _reserve_seqnum(self) -> int:
        current = self._next_seqnum
        self._next_seqnum += 1
        return current

    def _queue(self, key: str, package_id: int, kind: str, request: Message) -> None:
        if key in self._commands_by_key:
            return
        command = PendingWorldCommand(
            key=key,
            seqnum=request.seqnum,
            package_id=package_id,
            kind=kind,
            request=request,
        )
        self._commands_by_key[key] = command
        self._commands_by_seq[command.seqnum] = command

    def queue_purchase(self, package_id: int, warehouse_id: int, product_name: str, quantity: int) -> None:
        seqnum = self._reserve_seqnum()
        request = world_amazon_pb2.APurchaseMore(whnum=warehouse_id, seqnum=seqnum)
        request.things.add(id=package_id, description=product_name, count=quantity)
        self._queue(f"buy:{package_id}", package_id, "buy", request)

    def queue_pack(self, package_id: int, warehouse_id: int, product_name: str, quantity: int) -> None:
        seqnum = self._reserve_seqnum()
        request = world_amazon_pb2.APack(whnum=warehouse_id, shipid=package_id, seqnum=seqnum)
        request.things.add(id=package_id, description=product_name, count=quantity)
        self._queue(f"pack:{package_id}", package_id, "pack", request)

    def queue_load(self, package_id: int, warehouse_id: int, truck_id: int) -> None:
        seqnum = self._reserve_seqnum()
        request = world_amazon_pb2.APutOnTruck(
            whnum=warehouse_id,
            truckid=truck_id,
            shipid=package_id,
            seqnum=seqnum,
        )
        self._queue(f"load:{package_id}", package_id, "load", request)

    def _build_commands_message(self, commands: list[PendingWorldCommand]) -> world_amazon_pb2.ACommands:
        envelope = world_amazon_pb2.ACommands()
        envelope.simspeed = self.settings.world_sim_speed
        for ack in sorted(self._pending_response_acks):
            envelope.acks.append(ack)
        self._pending_response_acks.clear()

        for command in commands:
            if command.kind == "buy":
                envelope.buy.append(command.request)
            elif command.kind == "pack":
                envelope.topack.append(command.request)
            elif command.kind == "load":
                envelope.load.append(command.request)
            command.last_sent_at = time.monotonic()
        return envelope

    def _send_pending(self) -> None:
        if self._socket is None:
            return
        now = time.monotonic()
        sendable = [
            command
            for command in self._commands_by_seq.values()
            if not command.completed and (not command.acked or now - command.last_sent_at >= self._retry_interval)
        ]
        if not sendable and not self._pending_response_acks:
            return
        self._send_message(self._build_commands_message(sendable))

    def _complete(self, seqnum: int) -> None:
        command = self._commands_by_seq.get(seqnum)
        if command is None:
            return
        command.completed = True
        self._commands_by_key.pop(command.key, None)
        self._commands_by_seq.pop(seqnum, None)

    def _handle_error(self, db: Session, error: world_amazon_pb2.AErr) -> None:
        self._pending_response_acks.add(error.seqnum)
        command = self._commands_by_seq.get(error.originseqnum)
        if command is not None:
            mark_failure(db, command.package_id, f"World {command.kind} failed: {error.err}")
            self._complete(command.seqnum)

    def _handle_responses(self, db: Session, response: world_amazon_pb2.AResponses) -> None:
        for ack in response.acks:
            command = self._commands_by_seq.get(ack)
            if command is not None:
                command.acked = True

        for arrived in response.arrived:
            self._pending_response_acks.add(arrived.seqnum)
            mark_inventory_arrived(db, int(arrived.things[0].id))
            self._complete(arrived.seqnum)

        for ready in response.ready:
            self._pending_response_acks.add(ready.seqnum)
            mark_packed(db, int(ready.shipid))
            self._complete(ready.seqnum)

        for loaded in response.loaded:
            self._pending_response_acks.add(loaded.seqnum)
            mark_loaded(db, int(loaded.shipid))
            self._complete(loaded.seqnum)

        for error in response.error:
            self._handle_error(db, error)

        for package_status in response.packagestatus:
            self._pending_response_acks.add(package_status.seqnum)

        if response.finished:
            self.close()

    def sync_once(self, db: Session) -> None:
        try:
            self.connect(db)
            self._send_pending()
            while True:
                response = self._recv_message(world_amazon_pb2.AResponses, timeout=0.1)
                if response is None:
                    break
                self._handle_responses(db, response)
        except (ConnectionError, OSError):
            self.close()
            raise
