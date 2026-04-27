from __future__ import annotations

import logging
import time

from app.db import SessionLocal
from app.config import get_settings
from app.integrations.ups_client import UPSClient, UPSClientError
from app.integrations.world_client import WorldClient
from app.schemas.ups_api import PackageLoadedRequest, PickupRequest
from app.services.order_service import (
    get_shipments_needing_delivery_notice,
    get_shipments_needing_inventory,
    get_shipments_needing_load,
    get_shipments_needing_pack,
    get_shipments_needing_pickup,
    mark_delivery_notified,
    mark_failure,
    mark_inventory_requested,
    mark_load_requested,
    mark_pack_requested,
    mark_pickup_requested,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class FulfillmentWorker:
    def __init__(self) -> None:
        self.world = WorldClient()
        self.ups = UPSClient()

    def _sync_world_or_log(self, db) -> None:
        try:
            self.world.sync_once(db)
        except Exception:
            logger.exception(
                "world sync failed against %s:%s; continuing with HTTP integration work",
                self.world.settings.world_host,
                self.world.settings.world_port,
            )

    def run_once(self) -> None:
        with SessionLocal() as db:
            self._sync_world_or_log(db)

            for shipment in get_shipments_needing_pickup(db):
                order = shipment.order
                try:
                    response = self.ups.request_pickup(
                        PickupRequest(
                            package_id=shipment.package_id,
                            warehouse_id=shipment.warehouse_id,
                            dest_x=order.dest_x,
                            dest_y=order.dest_y,
                            ups_username=order.ups_username,
                        )
                    )
                    mark_pickup_requested(db, shipment.package_id, response.truck_id)
                except UPSClientError as exc:
                    mark_failure(db, shipment.package_id, str(exc))
                    logger.exception("pickup request failed for package %s", shipment.package_id)

            for shipment in get_shipments_needing_inventory(db):
                order = shipment.order
                self.world.queue_purchase(
                    package_id=shipment.package_id,
                    warehouse_id=shipment.warehouse_id,
                    product_name=order.product_name,
                    quantity=order.quantity,
                )
                if not shipment.inventory_requested:
                    mark_inventory_requested(db, shipment.package_id)

            for shipment in get_shipments_needing_pack(db):
                order = shipment.order
                self.world.queue_pack(
                    package_id=shipment.package_id,
                    warehouse_id=shipment.warehouse_id,
                    product_name=order.product_name,
                    quantity=order.quantity,
                )
                if not shipment.pack_requested:
                    mark_pack_requested(db, shipment.package_id)

            for shipment in get_shipments_needing_load(db):
                if shipment.truck_id is None:
                    continue
                self.world.queue_load(
                    package_id=shipment.package_id,
                    warehouse_id=shipment.warehouse_id,
                    truck_id=shipment.truck_id,
                )
                if not shipment.load_requested:
                    mark_load_requested(db, shipment.package_id)

            for shipment in get_shipments_needing_delivery_notice(db):
                order = shipment.order
                if shipment.truck_id is None:
                    continue
                try:
                    self.ups.notify_package_loaded(
                        PackageLoadedRequest(
                            package_id=shipment.package_id,
                            truck_id=shipment.truck_id,
                            dest_x=order.dest_x,
                            dest_y=order.dest_y,
                        )
                    )
                    mark_delivery_notified(db, shipment.package_id)
                except UPSClientError as exc:
                    mark_failure(db, shipment.package_id, str(exc))
                    logger.exception("package-loaded notification failed for package %s", shipment.package_id)

            self._sync_world_or_log(db)


def main() -> None:
    settings = get_settings()
    worker = FulfillmentWorker()
    logger.info("worker started")
    while True:
        try:
            worker.run_once()
        except Exception:
            logger.exception("worker loop failed")
        time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
