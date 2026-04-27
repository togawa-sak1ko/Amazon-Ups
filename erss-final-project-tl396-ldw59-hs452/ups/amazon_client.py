import json
import time
from urllib import error, request

from django.conf import settings


class AmazonProtocolError(RuntimeError):
    pass


class AmazonHttpClient:
    def __init__(self, base_url=None, timeout=5.0):
        preferred = (base_url or settings.AMAZON_BASE_URL).rstrip("/")
        fallback_candidates = [
            preferred,
            "http://127.0.0.1:8080",
            "http://localhost:8080",
            "http://host.docker.internal:8080",
            "http://amazon-server:8080",
            "http://amazon:8080",
        ]
        self.base_urls = []
        seen = set()
        for candidate in fallback_candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                self.base_urls.append(candidate)
        self.timeout = timeout

    def notify_truck_arrived(self, shipment):
        payload = {
            "truck_id": shipment.assigned_truck.truck_id,
            "warehouse_id": shipment.warehouse_id,
            "package_id": shipment.package_id,
        }
        return self._post_json("/truck-arrived", payload)

    def notify_package_delivered(self, shipment):
        payload = {"package_id": shipment.package_id}
        return self._post_json("/package-delivered", payload)

    def _post_json(self, path, payload):
        data = json.dumps(payload).encode("utf-8")
        last_error = None

        for base_url in self.base_urls:
            endpoint = f"{base_url}{path}"
            wait_seconds = 1
            for attempt in range(4):
                req = request.Request(
                    endpoint,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with request.urlopen(req, timeout=self.timeout) as response:
                        body = response.read().decode("utf-8").strip()
                        return json.loads(body) if body else {}
                except error.HTTPError as exc:
                    if 500 <= exc.code < 600 and attempt < 3:
                        last_error = exc
                        time.sleep(wait_seconds)
                        wait_seconds *= 2
                        continue
                    raise AmazonProtocolError(f"Amazon callback failed with HTTP {exc.code}.") from exc
                except error.URLError as exc:
                    last_error = exc
                    if attempt < 3:
                        time.sleep(wait_seconds)
                        wait_seconds *= 2
                        continue
                    break

        raise AmazonProtocolError("Amazon callback failed due to a network error.") from last_error
