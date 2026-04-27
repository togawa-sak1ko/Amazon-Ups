from __future__ import annotations

import time
from typing import Optional

import httpx

from app.config import get_settings
from app.schemas.ups_api import PackageLoadedRequest, PickupRequest, PickupResponse, RedirectRequest, RedirectResponse


class UPSClientError(RuntimeError):
    pass


class UPSClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _post_with_retry(self, path: str, payload: dict[str, object]) -> httpx.Response:
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                with httpx.Client(base_url=self.settings.ups_base_url, timeout=5.0) as client:
                    response = client.post(path, json=payload)
                if response.status_code >= 500:
                    raise UPSClientError(f"UPS {path} failed with {response.status_code}")
                if response.status_code >= 400:
                    detail = response.text
                    try:
                        detail = response.json().get("error", detail)
                    except ValueError:
                        pass
                    raise UPSClientError(f"UPS {path} rejected request: {detail}")
                return response
            except (httpx.HTTPError, UPSClientError) as exc:
                last_error = exc
                if attempt == 2 or (isinstance(exc, UPSClientError) and "rejected request" in str(exc)):
                    break
                time.sleep(2**attempt)
        raise UPSClientError(str(last_error) if last_error else f"UPS {path} failed")

    def request_pickup(self, payload: PickupRequest) -> PickupResponse:
        response = self._post_with_retry("/pickup", payload.model_dump(exclude_none=True))
        return PickupResponse.model_validate(response.json())

    def notify_package_loaded(self, payload: PackageLoadedRequest) -> None:
        self._post_with_retry("/package-loaded", payload.model_dump())

    def redirect_package(self, payload: RedirectRequest) -> RedirectResponse:
        response = self._post_with_retry("/redirect", payload.model_dump())
        return RedirectResponse.model_validate(response.json())

