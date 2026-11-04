"""Minimal async client for the Traccar REST API (tested against v4.x)."""

from __future__ import annotations

from typing import Any

import aiohttp
from yarl import URL

from ..models import Position
from .base import CannotConnect, Device, InvalidAuth

__all__ = [
    "CannotConnect",
    "Device",
    "InvalidAuth",
    "NotTraccar",
    "TraccarClient",
    "resolve_server",
    "server_urls",
]

# Pages of Traccar's web app and API. People paste whatever is in the address bar, so the
# server's base address is everything before the first of these.
_NOT_BASE_PATH = {
    "api",
    "change-server",
    "emulator",
    "event",
    "geofences",
    "login",
    "modern",
    "network",
    "position",
    "register",
    "replay",
    "reports",
    "reset-password",
    "settings",
}


class NotTraccar(CannotConnect):
    """Something answered at this address, but it doesn't behave like a Traccar server."""


def server_urls(raw: str) -> list[str]:
    """The base URLs to try for a pasted server address, most secure first.

    One URL if the address names its scheme; https then http if it doesn't. Keeps a reverse
    proxy's sub-path; drops logins, queries, fragments and pages of the web app.
    Raises ValueError if this can't be a web address.
    """
    text = raw.strip()
    has_scheme = "://" in text
    url = URL(text if has_scheme else f"http://{text}")
    if url.scheme not in ("http", "https") or not url.host or " " in text:
        raise ValueError("not a web address")
    kept: list[str] = []
    for segment in url.path.split("/"):
        if segment.lower() in _NOT_BASE_PATH or segment.lower().endswith(".html"):
            break
        if segment:
            kept.append(segment)
    base = (
        url.with_user(None).with_query(None).with_fragment(None).with_path("/".join(kept))
    )
    if has_scheme:
        return [str(base).rstrip("/")]
    return [str(base.with_scheme(scheme)).rstrip("/") for scheme in ("https", "http")]


async def resolve_server(session: aiohttp.ClientSession, raw: str) -> str:
    """The base URL to sign in to. An address with no scheme is probed without any login, so
    a password is only sent to a scheme that answers. Raises ValueError or CannotConnect."""
    urls = server_urls(raw)
    if len(urls) == 1:
        return urls[0]
    for url in urls:
        try:
            async with session.get(f"{url}/api/server", timeout=aiohttp.ClientTimeout(total=8)):
                return url
        except (aiohttp.ClientError, TimeoutError):
            continue
    raise CannotConnect(f"nothing answered at {urls[0]} or {urls[1]}")


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
                if 400 <= resp.status < 500:
                    raise NotTraccar(f"login returned HTTP {resp.status}")
                if resp.status != 200:
                    raise CannotConnect(f"login returned HTTP {resp.status}")
                # A signed-in Traccar answers with the user as JSON; a web page says 200 too.
                try:
                    user = await resp.json(content_type=None)
                except ValueError as err:
                    raise NotTraccar("login did not return JSON") from err
                if not isinstance(user, dict):
                    raise NotTraccar("login did not return a user")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(str(err)) from err

    async def _get(self, path: str, _retry: bool = True) -> list[Any]:
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
                try:
                    items = await resp.json(content_type=None)
                except ValueError as err:
                    raise NotTraccar(f"{path} did not return JSON") from err
                if not isinstance(items, list):
                    raise NotTraccar(f"{path} did not return a list")
                return items
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(str(err)) from err

    async def devices(self) -> list[Device]:
        try:
            return [
                Device(
                    id=str(d["id"]),
                    name=str(d.get("name") or d["id"]),
                    unique_id=str(d.get("uniqueId", "")),
                    status=d.get("status"),
                )
                for d in await self._get("/api/devices")
            ]
        except (AttributeError, KeyError, TypeError) as err:
            raise NotTraccar("/api/devices returned something unexpected") from err

    async def positions(self) -> list[Position]:
        """Latest known position of every device visible to this login."""
        result = []
        for raw in await self._get("/api/positions"):
            try:
                result.append(Position.from_traccar(raw))
            except (AttributeError, KeyError, ValueError, TypeError):
                continue  # skip malformed items rather than failing the refresh
        return result
