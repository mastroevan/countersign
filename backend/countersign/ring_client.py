"""Ring Partner API (Amazon Vision API) client.

Handles device discovery, end-to-end encryption checks, and WHEP live-view
session management over https://api.amazonvision.com.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_AVA_BASE_URL = "https://api.amazonvision.com"
DEFAULT_RING_TOKEN_ENV = "RING_ACCESS_TOKEN"
DEFAULT_RING_DOOR_DEVICE_ID_ENV = "RING_DOOR_DEVICE_ID"


class RingClientError(RuntimeError):
    """Base error for Ring API interactions."""


class RingTokenExpiredError(RingClientError):
    """The 30-minute Ring Playground token has expired (HTTP 401)."""


class RingDeviceInaccessibleError(RingClientError):
    """The device is offline, encrypted, or cannot be streamed."""


class RingClient:
    """Client for the Amazon Vision API / Ring Partner API."""

    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token = token or os.environ.get(DEFAULT_RING_TOKEN_ENV, "")
        self.base_url = (base_url or os.environ.get("RING_API_BASE_URL") or DEFAULT_AVA_BASE_URL).rstrip("/")
        self._http = http_client

    def _get_headers(self, token: str | None = None, content_type: str | None = None) -> dict[str, str]:
        t = token or self.token
        if not t:
            raise RingClientError(
                f"Ring access token missing. Set {DEFAULT_RING_TOKEN_ENV} or pass token."
            )
        headers = {"Authorization": f"Bearer {t}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _check_response_status(self, response: httpx.Response, action_description: str) -> None:
        if response.status_code == 401:
            raise RingTokenExpiredError(
                f"Ring token expired during {action_description}. Re-authenticate in Ring Playground."
            )
        if response.status_code == 503:
            raise RingDeviceInaccessibleError(
                f"Ring device temporarily unavailable (HTTP 503) during {action_description}."
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RingClientError(
                f"Ring API error ({response.status_code}) during {action_description}: {response.text}"
            ) from exc

    async def _request(
        self,
        method: str,
        url: str,
        action: str,
        headers: dict[str, str],
        http: httpx.AsyncClient | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        client = http or self._http
        if client is not None:
            r = await client.request(method, url, headers=headers, **kwargs)
        else:
            async with httpx.AsyncClient() as session:
                r = await session.request(method, url, headers=headers, **kwargs)
        if not (method == "DELETE" and r.status_code == 404):
            self._check_response_status(r, action)
        return r

    async def list_devices(
        self,
        token: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """List devices with status, capabilities, and configurations (JSON:API)."""
        r = await self._request(
            "GET",
            f"{self.base_url}/v1/devices",
            "list_devices",
            self._get_headers(token),
            http,
            params={"include": "status,capabilities,configurations"},
        )
        return r.json()  # type: ignore[no-any-return]

    async def find_door_device(
        self,
        token: str | None = None,
        preferred_device_id: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Find an accessible door camera device.

        Fails closed: a device is only returned when ``e2e_encryption.enabled``
        is explicitly ``false`` and it is not reported offline. A missing or
        unreadable encryption setting is treated as encrypted.
        """
        device_id = preferred_device_id or os.environ.get(DEFAULT_RING_DOOR_DEVICE_ID_ENV)
        doc = await self.list_devices(token=token, http=http)

        included_confs: dict[str, dict[str, Any]] = {}
        included_statuses: dict[str, dict[str, Any]] = {}
        for inc in doc.get("included", []):
            inc_type = inc.get("type")
            inc_id = inc.get("id")
            if inc_type == "configuration":
                included_confs[inc_id] = inc.get("attributes", {})
            elif inc_type == "status":
                included_statuses[inc_id] = inc.get("attributes", {})

        devices = doc.get("data", [])
        if not devices:
            raise RingDeviceInaccessibleError("No Ring devices found on account.")

        selected: dict[str, Any] | None = None
        for dev in devices:
            if device_id and str(dev.get("id")) != str(device_id):
                continue
            if not _e2e_disabled(dev, included_confs):
                continue
            if not _is_online(dev, included_statuses):
                continue
            selected = dev
            break

        if not selected:
            if device_id:
                raise RingDeviceInaccessibleError(
                    f"Specified device {device_id} is encrypted (or encryption "
                    "status unknown), offline, or not found."
                )
            raise RingDeviceInaccessibleError(
                "No accessible unencrypted door camera found among account devices."
            )
        return selected

    async def start_whep(
        self,
        device_id: str,
        offer_sdp: str,
        token: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> tuple[str, str | None]:
        """Start a WHEP session.

        Returns (answer_sdp, session_id_or_url).
        """
        r = await self._request(
            "POST",
            f"{self.base_url}/v1/devices/{device_id}/media/streaming/whep/sessions",
            f"start_whep({device_id})",
            self._get_headers(token, content_type="application/sdp"),
            http,
            content=offer_sdp,
        )
        return r.text, r.headers.get("Location")

    async def stop_whep(
        self,
        device_id: str,
        session_id_or_url: str,
        token: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        """Teardown a WHEP streaming session. Never raises: this runs in cleanup."""
        if session_id_or_url.startswith(("http://", "https://")):
            url = session_id_or_url
        else:
            url = f"{self.base_url}/v1/devices/{device_id}/media/streaming/whep/sessions/{session_id_or_url}"
        try:
            await self._request(
                "DELETE", url, f"stop_whep({device_id})", self._get_headers(token), http
            )
        except (httpx.HTTPError, RingClientError):
            pass


def _e2e_disabled(dev: dict[str, Any], included_confs: dict[str, dict[str, Any]]) -> bool:
    """True only if encryption is explicitly disabled and never reported enabled."""
    attrs = dev.get("attributes", {})
    values: list[Any] = []

    config = attrs.get("configurations") or attrs.get("configuration")
    if isinstance(config, dict):
        values.append((config.get("e2e_encryption") or {}).get("enabled"))

    rel = (dev.get("relationships", {}).get("configurations") or {}).get("data")
    if isinstance(rel, dict) and rel.get("id") in included_confs:
        values.append((included_confs[rel["id"]].get("e2e_encryption") or {}).get("enabled"))

    # Every source that reports must say False, and at least one must report.
    return bool(values) and all(v is False for v in values)


def _is_online(dev: dict[str, Any], included_statuses: dict[str, dict[str, Any]]) -> bool:
    attrs = dev.get("attributes", {})
    status = attrs.get("status")
    if isinstance(status, dict) and status.get("online") is False:
        return False
    rel = (dev.get("relationships", {}).get("status") or {}).get("data")
    if isinstance(rel, dict) and rel.get("id") in included_statuses:
        if included_statuses[rel["id"]].get("online") is False:
            return False
    return True


# Standalone functions matching blueprint specification
async def list_devices(http: httpx.AsyncClient, token: str) -> dict[str, Any]:
    client = RingClient(token=token, http_client=http)
    return await client.list_devices()


async def start_whep(
    http: httpx.AsyncClient, token: str, device_id: str, offer_sdp: str
) -> tuple[str, str | None]:
    client = RingClient(token=token, http_client=http)
    return await client.start_whep(device_id, offer_sdp)


async def stop_whep(
    http: httpx.AsyncClient, token: str, device_id: str, session_id: str
) -> None:
    client = RingClient(token=token, http_client=http)
    await client.stop_whep(device_id, session_id)
