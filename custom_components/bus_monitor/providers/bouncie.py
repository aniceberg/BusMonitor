"""Minimal async client for the Bouncie REST API (https://docs.bouncie.dev)."""

from __future__ import annotations

from typing import Any, Protocol

import aiohttp

from ..models import Position
from .base import CannotConnect, Device, InvalidAuth

API_BASE = "https://api.bouncie.dev/v1"
AUTHORIZE_URL = "https://auth.bouncie.com/dialog/authorize"
TOKEN_URL = "https://auth.bouncie.com/oauth/token"
PAGE_SIZE = 50


class TokenSource(Protocol):
    """Anything holding an OAuth token; Home Assistant's OAuth2Session fits."""

    @property
    def token(self) -> dict: ...

    async def async_ensure_token_valid(self) -> None: ...


class FixedToken:
    """A token that is used as is, e.g. one just issued during the config flow."""

    def __init__(self, token: dict) -> None:
        self.token = token

    async def async_ensure_token_valid(self) -> None:
        return None


def vehicle_name(raw: dict[str, Any]) -> str:
    """The vehicle's nickname, else '2021 Ford Transit', else its IMEI."""
    if nick := str(raw.get("nickName") or "").strip():
        return nick
    model = raw.get("model") or {}
    parts = [str(model[k]) for k in ("year", "make", "name") if model.get(k)]
    return " ".join(parts) or str(raw["imei"])


class BouncieClient:
    """Reads vehicles and their last known location for one Bouncie user."""

    name = "Bouncie"
    manufacturer = "Bouncie"

    def __init__(self, session: aiohttp.ClientSession, auth: TokenSource) -> None:
        self._session = session
        self._auth = auth

    async def login(self) -> None:
        await self.user()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            await self._auth.async_ensure_token_valid()
        except aiohttp.ClientResponseError as err:
            if 400 <= err.status < 500:
                raise InvalidAuth from err
            raise CannotConnect(f"token refresh returned HTTP {err.status}") from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(str(err) or type(err).__name__) from err
        try:
            async with self._session.get(
                f"{API_BASE}{path}",
                params=params,
                headers={
                    "Authorization": self._auth.token["access_token"],
                    "Accept": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status in (401, 403):
                    raise InvalidAuth
                if resp.status != 200:
                    raise CannotConnect(f"{path} returned HTTP {resp.status}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(str(err) or type(err).__name__) from err

    async def user(self) -> dict[str, Any]:
        """The signed-in Bouncie user: {id, email, name}."""
        return await self._get("/user")

    async def vehicles(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        while True:
            page = await self._get("/vehicles", {"limit": PAGE_SIZE, "skip": len(out)})
            if not isinstance(page, list):
                raise CannotConnect("/vehicles returned an unexpected response")
            out += page
            if len(page) < PAGE_SIZE:
                return out

    async def devices(self) -> list[Device]:
        return [
            Device(id=str(v["imei"]), name=vehicle_name(v), unique_id=str(v.get("vin") or ""))
            for v in await self.vehicles()
            if v.get("imei")
        ]

    async def positions(self) -> list[Position]:
        """Last known position of every vehicle; vehicles with no location are left out."""
        result = []
        for raw in await self.vehicles():
            try:
                if pos := Position.from_bouncie(raw):
                    result.append(pos)
            except (KeyError, ValueError, TypeError):
                continue  # skip malformed items rather than failing the refresh
        return result
