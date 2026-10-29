"""Minimal async client for the Traccar REST API (tested against v4.x)."""

from __future__ import annotations

from typing import Any

import aiohttp

from ..models import Position
from .base import CannotConnect, Device, InvalidAuth

__all__ = ["CannotConnect", "Device", "InvalidAuth", "TraccarClient"]


class TraccarClient:
    """Cookie-session client. Pass a session that has its own cookie jar."""

    name = "Traccar"
    manufacturer = "Traccar"

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        email: str,
        password: str,
    ) -> None:
        self._session = session
        self._base = base_url.rstrip("/")
        self._email = email
        self._password = password

    async def login(self) -> None:
        try:
            async with self._session.post(
                f"{self._base}/api/session",
                data={"email": self._email, "password": self._password},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status in (401, 403):
                    raise InvalidAuth
                if resp.status != 200:
                    raise CannotConnect(f"login returned HTTP {resp.status}")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(str(err)) from err

    async def _get(self, path: str, _retry: bool = True) -> Any:
        try:
            async with self._session.get(
                f"{self._base}{path}",
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 401 and _retry:
                    await self.login()
                    return await self._get(path, _retry=False)
                if resp.status == 401:
                    raise InvalidAuth
                if resp.status != 200:
                    raise CannotConnect(f"{path} returned HTTP {resp.status}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(str(err)) from err

    async def devices(self) -> list[Device]:
        return [
            Device(
                id=str(d["id"]),
                name=str(d.get("name") or d["id"]),
                unique_id=str(d.get("uniqueId", "")),
                status=d.get("status"),
            )
            for d in await self._get("/api/devices")
        ]

    async def positions(self) -> list[Position]:
        """Latest known position of every device visible to this login."""
        result = []
        for raw in await self._get("/api/positions"):
            try:
                result.append(Position.from_traccar(raw))
            except (KeyError, ValueError, TypeError):
                continue  # skip malformed items rather than failing the refresh
        return result
