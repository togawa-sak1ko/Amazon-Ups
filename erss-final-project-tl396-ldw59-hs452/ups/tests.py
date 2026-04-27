import io
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import OperationalError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .middleware import SetupErrorMiddleware
from .models import (
    SavedQuote,
    Shipment,
    ShipmentEvent,
    ShipmentStatus,
    SupportTicket,
    SupportTicketCategory,
    Truck,
    WorldCommand,
    WorldCommandStatus,
    WorldSession,
)
from .management.commands.run_world_daemon import Command as RunWorldDaemonCommand
from .services import (
    create_shipment_from_amazon,
    mark_shipment_delivered,
    mark_shipment_waiting,
    record_world_command_error,
    redirect_shipment,
)
from .world.client import WorldSocketClient


User = get_user_model()


class ShipmentServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="secretpass123")
        self.world_session = WorldSession.objects.create(name="primary", world_id=1001)
        self.truck = Truck.objects.create(world_session=self.world_session, truck_id=1)

    def test_create_shipment_links_owner_and_queues_pickup(self):
        shipment = create_shipment_from_amazon(
            {
                "world_id": self.world_session.world_id,
                "package_id": 77,
                "warehouse_id": 2,
                "destination_x": 9,
                "destination_y": 4,
                "owner_username": "alice",
                "items": [{"description": "Router", "quantity": 1}],
            }
        )

        self.assertEqual(shipment.owner, self.user)
        self.assertEqual(shipment.status, ShipmentStatus.EN_ROUTE_TO_WAREHOUSE)
        self.assertEqual(shipment.items.count(), 1)
        self.assertEqual(shipment.world_commands.count(), 1)

    def test_redirect_blocks_after_out_for_delivery(self):
        shipment = Shipment.objects.create(
            world_session=self.world_session,
            package_id=88,
            tracking_number="UPS-TEST88",
            warehouse_id=3,
            destination_x=4,
            destination_y=5,
            status=ShipmentStatus.OUT_FOR_DELIVERY,
        )

        with self.assertRaises(ValueError):
            redirect_shipment(shipment, 10, 11)


class ShipmentApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.world_session = WorldSession.objects.create(name="api-session", world_id=2222)
        self.truck = Truck.objects.create(world_session=self.world_session, truck_id=7)
        self.shipment = Shipment.objects.create(
            world_session=self.world_session,
            package_id=99,
            tracking_number="UPS-TRACK99",
            warehouse_id=1,
            destination_x=1,
            destination_y=2,
            status=ShipmentStatus.CREATED,
        )

    def test_status_api_returns_tracking_payload(self):
        response = self.client.get(reverse("ups:shipment-status-api", args=[self.shipment.tracking_number]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tracking_number"], self.shipment.tracking_number)

    def test_shipping_overview_page_renders(self):
        response = self.client.get(reverse("ups:shipping-overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shipping control center")

    def test_pickup_endpoint_matches_protocol_spec(self):
        response = self.client.post(
            reverse("ups:pickup-api"),
            data='{"world_id": 2222, "package_id": 555, "warehouse_id": 8, "dest_x": 4, "dest_y": 6, "ups_username": "alice"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"truck_id": self.truck.truck_id})
        shipment = Shipment.objects.get(package_id=555)
        self.assertEqual(shipment.tracking_number, "555")
        self.assertEqual(shipment.owner_reference, "alice")

    def test_package_loaded_endpoint_marks_out_for_delivery(self):
        shipment = create_shipment_from_amazon(
            {
                "world_id": self.world_session.world_id,
                "package_id": 556,
                "warehouse_id": 8,
                "dest_x": 4,
                "dest_y": 6,
            }
        )

        response = self.client.post(
            reverse("ups:package-loaded-api"),
            data='{"package_id": 556, "truck_id": 7, "dest_x": 10, "dest_y": 11}',
            content_type="application/json",
        )

        shipment.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {})
        self.assertEqual(shipment.status, ShipmentStatus.OUT_FOR_DELIVERY)
        self.assertEqual(shipment.destination_x, 10)
        self.assertEqual(shipment.destination_y, 11)

    def test_redirect_endpoint_returns_success_false_after_dispatch(self):
        self.shipment.status = ShipmentStatus.OUT_FOR_DELIVERY
        self.shipment.save(update_fields=["status", "updated_at"])

        response = self.client.post(
            reverse("ups:redirect-by-package-api"),
            data='{"package_id": 99, "dest_x": 8, "dest_y": 8}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["success"], False)
        self.assertIn("can no longer be redirected", response.json()["message"])


class PortalWorkflowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="portaluser",
            email="portal@example.com",
            password="secretpass123",
        )
        self.world_session = WorldSession.objects.create(name="portal", world_id=3003)
        self.truck = Truck.objects.create(world_session=self.world_session, truck_id=9)
        self.shipment = Shipment.objects.create(
            world_session=self.world_session,
            package_id=123,
            tracking_number="UPS-PORTAL123",
            warehouse_id=4,
            destination_x=12,
            destination_y=18,
            owner=self.user,
            owner_reference=self.user.username,
            assigned_truck=self.truck,
            status=ShipmentStatus.EN_ROUTE_TO_WAREHOUSE,
        )
        ShipmentEvent.objects.create(
            shipment=self.shipment,
            event_type="pickup_queued",
            message="Queued pickup request for truck 9.",
        )

    def test_quote_overview_saves_estimate(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("ups:quote-overview"),
            {
                "service_level": "ground",
                "origin_x": 1,
                "origin_y": 1,
                "destination_x": 9,
                "destination_y": 4,
                "package_count": 2,
                "total_weight_lbs": "5.50",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(SavedQuote.objects.count(), 1)
        self.assertContains(response, "Estimate saved")

    def test_signup_creates_account_and_logs_user_in(self):
        response = self.client.post(
            reverse("ups:signup"),
            {
                "username": "newportaluser",
                "email": "newportal@example.com",
                "password1": "portal-pass-123",
                "password2": "portal-pass-123",
            },
        )

        created_user = User.objects.get(username="newportaluser")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("ups:dashboard"))
        self.assertEqual(self.client.session["_auth_user_id"], str(created_user.pk))

    def test_signup_invalid_password_shows_clear_feedback(self):
        response = self.client.post(
            reverse("ups:signup"),
            {
                "username": "weakpassworduser",
                "email": "weakpassword@example.com",
                "password1": "short",
                "password2": "short",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "We could not create your account yet.")
        self.assertContains(response, "Use at least 8 characters")
        self.assertContains(response, "This password is too short")

    def test_home_tracking_lookup_accepts_package_id_and_redirects(self):
        response = self.client.post(reverse("ups:home"), {"tracking_number": str(self.shipment.package_id)})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("ups:tracking-result", args=[self.shipment.tracking_number]))

    def test_home_tracking_lookup_invalid_stays_on_page_with_error(self):
        response = self.client.post(reverse("ups:home"), {"tracking_number": "NOT-A-REAL-PACKAGE"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tracking number invalid or not found.")
        self.assertTemplateUsed(response, "ups/tracking_lookup.html")

    def test_support_center_creates_ticket(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("ups:support-center"),
            {
                "email": self.user.email,
                "tracking_number": self.shipment.tracking_number,
                "category": SupportTicketCategory.TRACKING,
                "subject": "Missing movement update",
                "message": "The package has not updated in the portal.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(SupportTicket.objects.count(), 1)
        self.assertContains(response, "Missing movement update")

    def test_search_results_finds_shipment(self):
        response = self.client.get(reverse("ups:search-results"), {"query": self.shipment.tracking_number})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.shipment.tracking_number)

    def test_locations_center_filters_results(self):
        response = self.client.get(reverse("ups:locations-center"), {"query": "Durham"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Durham Customer Center")
        self.assertNotContains(response, "Raleigh Operations Center")

    def test_alerts_center_shows_shipment_and_support_activity(self):
        SupportTicket.objects.create(
            owner=self.user,
            email=self.user.email,
            tracking_number=self.shipment.tracking_number,
            category=SupportTicketCategory.TRACKING,
            subject="Package still loading",
            message="Please confirm the latest package state.",
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("ups:alerts-center"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.shipment.tracking_number)
        self.assertContains(response, "Package still loading")


class AmazonNotificationTests(TestCase):
    def setUp(self):
        self.world_session = WorldSession.objects.create(name="notify-world", world_id=4444)
        self.truck = Truck.objects.create(world_session=self.world_session, truck_id=12)
        self.shipment = Shipment.objects.create(
            world_session=self.world_session,
            package_id=600,
            tracking_number="600",
            warehouse_id=3,
            destination_x=7,
            destination_y=9,
            assigned_truck=self.truck,
            status=ShipmentStatus.EN_ROUTE_TO_WAREHOUSE,
        )

    @patch("ups.services.AmazonHttpClient.notify_truck_arrived")
    def test_mark_shipment_waiting_notifies_amazon(self, notify_truck_arrived):
        notify_truck_arrived.return_value = {}

        mark_shipment_waiting(self.shipment, self.truck)

        notify_truck_arrived.assert_called_once()
        self.assertTrue(
            self.shipment.events.filter(event_type="amazon_truck_arrived_notified").exists()
        )

    @patch("ups.services.AmazonHttpClient.notify_package_delivered")
    def test_mark_shipment_delivered_notifies_amazon(self, notify_delivered):
        notify_delivered.return_value = {}

        mark_shipment_delivered(self.shipment)

        notify_delivered.assert_called_once()
        self.assertTrue(
            self.shipment.events.filter(event_type="amazon_delivery_notified").exists()
        )


class SetupErrorMiddlewareTests(TestCase):
    def test_setup_error_is_rendered_for_missing_tables(self):
        middleware = SetupErrorMiddleware(lambda request: None)
        response = middleware.process_exception(
            request=self.client.request().wsgi_request,
            exception=OperationalError("no such table: ups_shipment"),
        )

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"Mini-UPS is not fully initialized yet", response.content)


class FakeRepeatedField(list):
    def __init__(self, factory):
        super().__init__()
        self.factory = factory

    def add(self):
        item = self.factory()
        self.append(item)
        return item


class FakePickupMessage:
    def __init__(self):
        self.truckid = None
        self.whid = None
        self.seqnum = None


class FakeDeliveryLocationMessage:
    def __init__(self):
        self.packageid = None
        self.x = None
        self.y = None


class FakeDeliveryMessage:
    def __init__(self):
        self.truckid = None
        self.seqnum = None
        self.packages = FakeRepeatedField(FakeDeliveryLocationMessage)


class FakeQueryMessage:
    def __init__(self):
        self.truckid = None
        self.seqnum = None


class FakeUCommandsMessage:
    def __init__(self):
        self.pickups = FakeRepeatedField(FakePickupMessage)
        self.deliveries = FakeRepeatedField(FakeDeliveryMessage)
        self.queries = FakeRepeatedField(FakeQueryMessage)
        self.acks = []


class WorldSocketClientDispatchTests(TestCase):
    def setUp(self):
        self.world_session = WorldSession.objects.create(name="dispatch-world", world_id=5555)
        self.truck = Truck.objects.create(world_session=self.world_session, truck_id=3)
        self.shipment = Shipment.objects.create(
            world_session=self.world_session,
            package_id=701,
            tracking_number="UPS-DISPATCH701",
            warehouse_id=9,
            destination_x=17,
            destination_y=21,
            assigned_truck=self.truck,
            status=ShipmentStatus.CREATED,
        )
        self.client = WorldSocketClient(host="world", port=12345)
        self.fake_pb2 = SimpleNamespace(UCommands=FakeUCommandsMessage)

    def test_dispatch_pickup_maps_payload_and_marks_sent(self):
        command = WorldCommand.objects.create(
            world_session=self.world_session,
            shipment=self.shipment,
            truck=self.truck,
            seq_num=101,
            command_type="pickup",
            payload={"truck_id": 3, "warehouse_id": 9, "package_id": 701},
        )

        with patch.object(self.client, "require_proto_bindings", return_value=self.fake_pb2):
            with patch.object(self.client, "send") as send_mock:
                message = self.client.dispatch(command)

        command.refresh_from_db()
        self.assertEqual(command.status, WorldCommandStatus.SENT)
        self.assertEqual(len(message.pickups), 1)
        self.assertEqual(message.pickups[0].truckid, 3)
        self.assertEqual(message.pickups[0].whid, 9)
        self.assertEqual(message.pickups[0].seqnum, 101)
        send_mock.assert_called_once()

    def test_dispatch_delivery_supports_multiple_dropoffs(self):
        command = WorldCommand.objects.create(
            world_session=self.world_session,
            shipment=self.shipment,
            truck=self.truck,
            seq_num=102,
            command_type="deliveries",
            payload={
                "truck_id": 3,
                "packages": [
                    {"package_id": 701, "x": 17, "y": 21},
                    {"package_id": 702, "x": 5, "y": 6},
                ],
            },
        )

        with patch.object(self.client, "require_proto_bindings", return_value=self.fake_pb2):
            with patch.object(self.client, "send"):
                message = self.client.dispatch(command)

        command.refresh_from_db()
        self.assertEqual(command.status, WorldCommandStatus.SENT)
        self.assertEqual(len(message.deliveries), 1)
        self.assertEqual(message.deliveries[0].truckid, 3)
        self.assertEqual(message.deliveries[0].seqnum, 102)
        self.assertEqual(len(message.deliveries[0].packages), 2)
        self.assertEqual(message.deliveries[0].packages[1].packageid, 702)
        self.assertEqual(message.deliveries[0].packages[1].x, 5)
        self.assertEqual(message.deliveries[0].packages[1].y, 6)

    def test_dispatch_rejects_unsupported_command_type(self):
        command = WorldCommand.objects.create(
            world_session=self.world_session,
            shipment=self.shipment,
            truck=self.truck,
            seq_num=103,
            command_type="teleport",
            payload={"truck_id": 3},
        )

        with patch.object(self.client, "require_proto_bindings", return_value=self.fake_pb2):
            with self.assertRaises(ValueError):
                self.client.dispatch(command)

        command.refresh_from_db()
        self.assertEqual(command.status, WorldCommandStatus.PENDING)


class WorldSocketClientResponseTests(TestCase):
    def setUp(self):
        self.world_session = WorldSession.objects.create(name="response-world", world_id=6666)
        self.truck = Truck.objects.create(world_session=self.world_session, truck_id=4)
        self.shipment = Shipment.objects.create(
            world_session=self.world_session,
            package_id=801,
            tracking_number="UPS-RESP801",
            warehouse_id=6,
            destination_x=13,
            destination_y=19,
            assigned_truck=self.truck,
            status=ShipmentStatus.EN_ROUTE_TO_WAREHOUSE,
        )
        self.client = WorldSocketClient(host="world", port=12345)
        self.fake_pb2 = SimpleNamespace(UCommands=FakeUCommandsMessage)

    def test_process_world_response_marks_commands_acked(self):
        command = WorldCommand.objects.create(
            world_session=self.world_session,
            shipment=self.shipment,
            truck=self.truck,
            seq_num=210,
            command_type="pickup",
            payload={"truck_id": 4, "warehouse_id": 6},
            status=WorldCommandStatus.SENT,
        )
        response = SimpleNamespace(
            acks=[210],
            completions=[],
            delivered=[],
            truckstatus=[],
            error=[],
        )

        with patch.object(self.client, "require_proto_bindings", return_value=self.fake_pb2):
            with patch.object(self.client, "send") as send_mock:
                summary = self.client.process_world_response(self.world_session, response, notify_amazon=False)

        command.refresh_from_db()
        self.assertEqual(command.status, WorldCommandStatus.ACKED)
        self.assertEqual(summary["acked_commands"], 1)
        send_mock.assert_not_called()

    def test_process_world_response_handles_completion_and_sends_ack(self):
        command = WorldCommand.objects.create(
            world_session=self.world_session,
            shipment=self.shipment,
            truck=self.truck,
            seq_num=211,
            command_type="pickup",
            payload={"truck_id": 4, "warehouse_id": 6},
            status=WorldCommandStatus.SENT,
        )
        response = SimpleNamespace(
            acks=[],
            completions=[
                SimpleNamespace(
                    truckid=4,
                    x=2,
                    y=3,
                    status="arrive warehouse",
                    seqnum=211,
                )
            ],
            delivered=[],
            truckstatus=[],
            error=[],
        )

        with patch.object(self.client, "require_proto_bindings", return_value=self.fake_pb2):
            with patch.object(self.client, "send") as send_mock:
                summary = self.client.process_world_response(self.world_session, response, notify_amazon=False)

        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.WAITING_FOR_PICKUP)
        self.assertEqual(summary["completions"], 1)
        send_mock.assert_called_once()
        ack_message = send_mock.call_args[0][0]
        self.assertEqual(ack_message.acks, [211])
        command.refresh_from_db()
        self.assertIsNotNone(command.completed_at)

    def test_process_world_response_handles_delivery_and_truck_status(self):
        command = WorldCommand.objects.create(
            world_session=self.world_session,
            shipment=self.shipment,
            truck=self.truck,
            seq_num=214,
            command_type="deliver",
            payload={"truck_id": 4, "package_id": 801, "destination_x": 13, "destination_y": 19},
            status=WorldCommandStatus.ACKED,
        )
        self.shipment.status = ShipmentStatus.OUT_FOR_DELIVERY
        self.shipment.save(update_fields=["status", "updated_at"])
        response = SimpleNamespace(
            acks=[],
            completions=[],
            delivered=[SimpleNamespace(truckid=4, packageid=801, seqnum=312)],
            truckstatus=[SimpleNamespace(truckid=4, status="idle", x=9, y=10, seqnum=313)],
            error=[],
        )

        with patch.object(self.client, "require_proto_bindings", return_value=self.fake_pb2):
            with patch.object(self.client, "send") as send_mock:
                summary = self.client.process_world_response(self.world_session, response, notify_amazon=False)

        self.shipment.refresh_from_db()
        self.truck.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.DELIVERED)
        self.assertEqual(self.truck.status, "idle")
        self.assertEqual(self.truck.current_x, 9)
        self.assertEqual(self.truck.current_y, 10)
        self.assertEqual(summary["delivered"], 1)
        self.assertEqual(summary["truckstatus"], 1)
        command.refresh_from_db()
        self.assertIsNotNone(command.completed_at)
        send_mock.assert_called_once()
        ack_message = send_mock.call_args[0][0]
        self.assertEqual(ack_message.acks, [312, 313])

    def test_process_world_response_exposes_finished_flag(self):
        response = SimpleNamespace(
            acks=[],
            completions=[],
            delivered=[],
            truckstatus=[],
            error=[],
            finished=True,
        )
        with patch.object(self.client, "require_proto_bindings", return_value=self.fake_pb2):
            with patch.object(self.client, "send"):
                summary = self.client.process_world_response(self.world_session, response, notify_amazon=False)
        self.assertTrue(summary["finished"])


class WorldSocketClientProtoBindingsTests(TestCase):
    def test_require_proto_bindings_loads_generated_world_ups_pb2(self):
        client = WorldSocketClient(host="world", port=12345)
        pb2 = client.require_proto_bindings()
        self.assertTrue(hasattr(pb2, "UCommands"))
        self.assertTrue(hasattr(pb2, "UResponses"))
        self.assertTrue(hasattr(pb2, "UConnect"))


class WorldSocketClientConnectTests(TestCase):
    def test_connect_world_sends_uconnect_and_returns_uconnected(self):
        client = WorldSocketClient(host="world", port=12345)
        fake_connected = SimpleNamespace(worldid=7, result="connected!")
        fake_pb2 = SimpleNamespace(UConnected=object)
        with patch.object(client, "require_proto_bindings", return_value=fake_pb2):
            with patch.object(client, "build_connect_message", return_value="uconnect-bytes") as build_mock:
                with patch.object(client, "send") as send_mock:
                    with patch.object(client, "receive", return_value=fake_connected) as recv_mock:
                        out = client.connect_world(world_id=None, trucks=[{"id": 1, "x": 0, "y": 0}])
        self.assertIs(out, fake_connected)
        build_mock.assert_called_once_with(world_id=None, trucks=[{"id": 1, "x": 0, "y": 0}])
        send_mock.assert_called_once_with("uconnect-bytes")
        recv_mock.assert_called_once()


class RunWorldDaemonConnectTests(TestCase):
    def test_connect_session_persists_world_and_sets_connected_flag(self):
        session = WorldSession.objects.create(name="connect-test", world_id=None, host="world", port=12345)
        Truck.objects.create(world_session=session, truck_id=1, current_x=2, current_y=3)
        client = WorldSocketClient(host="world", port=12345)
        connected = SimpleNamespace(worldid=4242, result="connected!")

        daemon = RunWorldDaemonCommand()
        daemon.stdout = io.StringIO()
        with patch.object(client, "connect_world", return_value=connected):
            daemon._connect_session_to_world(client, session)

        session.refresh_from_db()
        self.assertEqual(session.world_id, 4242)
        self.assertTrue(session.is_connected)

    def test_process_queue_polls_responses_when_no_pending_commands(self):
        session = WorldSession.objects.create(name="primary", world_id=9, host="world", port=12345)
        WorldCommand.objects.create(
            world_session=session,
            seq_num=77,
            command_type="query",
            payload={"truck_id": 1},
            status=WorldCommandStatus.ACKED,
        )
        daemon = RunWorldDaemonCommand()
        daemon.stdout = io.StringIO()
        daemon.stderr = io.StringIO()
        with patch("ups.management.commands.run_world_daemon.WorldSocketClient") as client_cls:
            client = client_cls.return_value
            with patch.object(daemon, "_connect_session_to_world") as connect_mock:
                with patch.object(daemon, "_consume_world_responses") as consume_mock:
                    daemon._process_queue()
        connect_mock.assert_called_once_with(client, session)
        consume_mock.assert_called_once_with(client, session)

    def test_consume_world_responses_marks_session_disconnected_on_finished(self):
        session = WorldSession.objects.create(
            name="primary",
            world_id=11,
            host="world",
            port=12345,
            is_connected=True,
        )
        client = MagicMock()
        client.require_proto_bindings.return_value = SimpleNamespace(UResponses=object)
        client.receive.return_value = SimpleNamespace()
        client.process_world_response.return_value = {
            "acked_commands": 0,
            "completions": 0,
            "delivered": 0,
            "truckstatus": 0,
            "errors": 0,
            "inbound_acks_sent": 0,
            "finished": True,
        }
        daemon = RunWorldDaemonCommand()
        daemon.stdout = io.StringIO()
        daemon.stderr = io.StringIO()

        daemon._consume_world_responses(client, session)

        session.refresh_from_db()
        self.assertFalse(session.is_connected)
        client.close.assert_called_once()

    @override_settings(UPS_WORLD_COMMAND_MAX_RETRIES=1)
    def test_process_queue_records_retry_metadata_when_dispatch_fails(self):
        session = WorldSession.objects.create(name="primary", world_id=22, host="world", port=12345)
        command = WorldCommand.objects.create(
            world_session=session,
            seq_num=333,
            command_type="pickup",
            payload={"truck_id": 1, "warehouse_id": 1},
            status=WorldCommandStatus.PENDING,
        )

        daemon = RunWorldDaemonCommand()
        daemon.stdout = io.StringIO()
        daemon.stderr = io.StringIO()

        with patch("ups.management.commands.run_world_daemon.WorldSocketClient") as client_cls:
            client = client_cls.return_value
            client.dispatch.side_effect = ValueError("dispatch failed")
            with patch.object(daemon, "_connect_session_to_world"):
                with patch.object(daemon, "_consume_world_responses"):
                    daemon._process_queue()

        command.refresh_from_db()
        self.assertEqual(command.retry_count, 1)
        self.assertEqual(command.status, WorldCommandStatus.PENDING)

    def test_retry_waiting_pickup_callbacks_retries_failed_truck_arrived_notification(self):
        session = WorldSession.objects.create(name="primary", world_id=23, host="world", port=12345)
        truck = Truck.objects.create(world_session=session, truck_id=1)
        shipment = Shipment.objects.create(
            world_session=session,
            package_id=909,
            tracking_number="UPS-RETRY909",
            warehouse_id=1,
            destination_x=3,
            destination_y=4,
            assigned_truck=truck,
            status=ShipmentStatus.WAITING_FOR_PICKUP,
        )
        ShipmentEvent.objects.create(
            shipment=shipment,
            event_type="amazon_callback_failed",
            message="previous failure",
        )
        daemon = RunWorldDaemonCommand()
        daemon.stdout = io.StringIO()

        with patch(
            "ups.management.commands.run_world_daemon.notify_amazon_truck_arrived_for_waiting_shipment",
            return_value=True,
        ) as notify_mock:
            daemon._retry_waiting_pickup_callbacks()

        notify_mock.assert_called_once()

    def test_process_queue_does_not_requeue_stale_deliver_for_delivered_shipment(self):
        session = WorldSession.objects.create(name="primary", world_id=24, host="world", port=12345)
        truck = Truck.objects.create(world_session=session, truck_id=1)
        shipment = Shipment.objects.create(
            world_session=session,
            package_id=910,
            tracking_number="UPS-DONE910",
            warehouse_id=1,
            destination_x=3,
            destination_y=4,
            assigned_truck=truck,
            status=ShipmentStatus.DELIVERED,
        )
        WorldCommand.objects.create(
            world_session=session,
            shipment=shipment,
            truck=truck,
            seq_num=400,
            command_type="deliver",
            payload={"truck_id": 1, "package_id": 910, "destination_x": 3, "destination_y": 4},
            status=WorldCommandStatus.ACKED,
            acked_at=timezone.now() - timedelta(seconds=60),
        )
        daemon = RunWorldDaemonCommand()
        daemon.stdout = io.StringIO()
        daemon.stderr = io.StringIO()

        with patch("ups.management.commands.run_world_daemon.WorldSocketClient") as client_cls:
            client = client_cls.return_value
            with patch.object(daemon, "_connect_session_to_world"):
                with patch.object(daemon, "_consume_world_responses"):
                    daemon._process_queue()

        self.assertEqual(
            WorldCommand.objects.filter(shipment=shipment, command_type="deliver").count(),
            1,
        )


class WorldCommandRetryTests(TestCase):
    @override_settings(UPS_WORLD_COMMAND_MAX_RETRIES=2)
    def test_record_world_command_error_requeues_until_cap_then_fails(self):
        session = WorldSession.objects.create(name="retry-world", world_id=1)
        command = WorldCommand.objects.create(
            world_session=session,
            seq_num=9001,
            command_type="pickup",
            payload={},
            status=WorldCommandStatus.SENT,
        )
        self.assertTrue(record_world_command_error(command, "first"))
        command.refresh_from_db()
        self.assertEqual(command.retry_count, 1)
        self.assertEqual(command.status, WorldCommandStatus.PENDING)

        command.status = WorldCommandStatus.SENT
        command.save(update_fields=["status", "updated_at"])
        self.assertTrue(record_world_command_error(command, "second"))
        command.refresh_from_db()
        self.assertEqual(command.retry_count, 2)
        self.assertEqual(command.status, WorldCommandStatus.PENDING)

        command.status = WorldCommandStatus.SENT
        command.save(update_fields=["status", "updated_at"])
        self.assertFalse(record_world_command_error(command, "third"))
        command.refresh_from_db()
        self.assertEqual(command.retry_count, 3)
        self.assertEqual(command.status, WorldCommandStatus.FAILED)


class SeedWorldSessionCommandTests(TestCase):
    def test_seed_world_session_creates_trucks(self):
        out = io.StringIO()
        call_command("seed_world_session", "--trucks", "2", stdout=out)
        session = WorldSession.objects.get(name="primary")
        self.assertEqual(session.trucks.count(), 2)
        self.assertTrue(session.trucks.filter(truck_id=1).exists())
        self.assertTrue(session.trucks.filter(truck_id=2).exists())


class SeedMockPortalDataCommandTests(TestCase):
    def test_seed_mock_portal_data_creates_demo_accounts_and_records(self):
        out = io.StringIO()

        call_command("seed_mock_portal_data", stdout=out)

        self.assertTrue(User.objects.filter(username="demo_customer").exists())
        self.assertTrue(User.objects.filter(username="demo_receiver").exists())
        self.assertTrue(Shipment.objects.filter(tracking_number="610001").exists())
        self.assertTrue(Shipment.objects.filter(tracking_number="UPS-MOCK-ROUTE").exists())
        self.assertEqual(Shipment.objects.get(package_id=610001).items.count(), 2)
        self.assertEqual(SupportTicket.objects.filter(owner__username="demo_customer").count(), 2)
        self.assertEqual(SavedQuote.objects.filter(created_by__username="demo_customer").count(), 2)
        self.assertIn("Mock Mini-UPS portal data is ready.", out.getvalue())
