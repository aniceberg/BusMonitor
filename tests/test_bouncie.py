"""Bouncie client and token handling (REST mocked; no real Bouncie account needed)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import ClientResponseError, RequestInfo
from homeassistant.components.application_credentials import ClientCredential
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import OAuth2TokenRequestReauthError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yarl import URL

from custom_components.bus_monitor.application_credentials import async_get_auth_implementation
from custom_components.bus_monitor.models import Position
from custom_components.bus_monitor.providers import CannotConnect, InvalidAuth
from custom_components.bus_monitor.providers.bouncie import (
    API_BASE,
    PAGE_SIZE,
    TOKEN_URL,
    BouncieClient,
    FixedToken,
    vehicle_name,
)


def vehicle(imei="353000000000001", nick="Carpool van", location=True, **stats):
    raw = {
        "imei": imei,
        "vin": "1FTBW3XM0LKA00001",
        "nickName": nick,
        "model": {"make": "Ford", "name": "Transit", "year": 2021},
        "stats": {
            "lastUpdated": "2026-10-28T12:30:05.000Z",
            "speed": 30,
            "isRunning": True,
            **stats,
        },
    }
    if location:
        raw["stats"]["location"] = {"lat": 40.1, "lon": -75.2, "heading": 90, "address": "1 Main St"}
    return raw


def test_position_from_bouncie_converts_mph():
    p = Position.from_bouncie(vehicle())
    assert p.device_id == "353000000000001"
    assert (p.lat, p.lon, p.course) == (40.1, -75.2, 90.0)
    assert abs(p.speed_mps - 13.4112) < 1e-4
    assert p.fix_time.utcoffset().total_seconds() == 0 and p.fix_time.second == 5


def test_position_from_bouncie_without_location_is_none():
    assert Position.from_bouncie(vehicle(location=False)) is None


def test_vehicle_name_falls_back_to_model_then_imei():
    assert vehicle_name(vehicle()) == "Carpool van"
    assert vehicle_name(vehicle(nick="")) == "2021 Ford Transit"
    assert vehicle_name({"imei": "42", "model": {}}) == "42"


def _client(hass, token=None):
    return BouncieClient(async_get_clientsession(hass), FixedToken(token or {"access_token": "tok"}))


async def test_positions_skip_vehicles_without_location(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(
        f"{API_BASE}/vehicles", json=[vehicle(), vehicle(imei="2", location=False)]
    )
    client = _client(hass)
    assert [p.device_id for p in await client.positions()] == ["353000000000001"]
    assert [d.id for d in await client.devices()] == ["353000000000001", "2"]
    headers = aioclient_mock.mock_calls[0][3]
    assert headers["Authorization"] == "tok"


async def test_vehicles_are_paged(hass: HomeAssistant, aioclient_mock):
    first = [vehicle(imei=str(i)) for i in range(PAGE_SIZE)]
    aioclient_mock.get(f"{API_BASE}/vehicles", params={"skip": PAGE_SIZE}, json=[vehicle(imei="last")])
    aioclient_mock.get(f"{API_BASE}/vehicles", params={"skip": 0}, json=first)
    devices = await _client(hass).devices()
    assert len(devices) == PAGE_SIZE + 1 and devices[-1].id == "last"


async def test_http_errors_are_mapped(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(f"{API_BASE}/user", status=401)
    with pytest.raises(InvalidAuth):
        await _client(hass).login()
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_BASE}/user", status=503)
    with pytest.raises(CannotConnect):
        await _client(hass).login()


async def test_failed_token_refresh_is_invalid_auth(hass: HomeAssistant):
    auth = AsyncMock()
    auth.token = {"access_token": "old"}
    info = RequestInfo(URL(TOKEN_URL), "POST", {}, URL(TOKEN_URL))
    auth.async_ensure_token_valid.side_effect = OAuth2TokenRequestReauthError(
        request_info=info, history=(), status=400, domain="bus_monitor"
    )
    with pytest.raises(InvalidAuth):
        await BouncieClient(async_get_clientsession(hass), auth).positions()

    auth.async_ensure_token_valid.side_effect = ClientResponseError(info, (), status=502)
    with pytest.raises(CannotConnect):
        await BouncieClient(async_get_clientsession(hass), auth).positions()


async def test_token_request_is_json(hass: HomeAssistant):
    resp = AsyncMock()
    resp.raise_for_status = lambda: None
    resp.json.return_value = {"access_token": "a", "refresh_token": "r2", "expires_in": 3600}
    session = AsyncMock()
    session.post.return_value = resp
    impl = await async_get_auth_implementation(
        hass, "bus_monitor", ClientCredential("cid", "secret")
    )
    with patch(
        "custom_components.bus_monitor.application_credentials.async_get_clientsession",
        return_value=session,
    ):
        token = await impl.async_refresh_token({"refresh_token": "r1", "access_token": "x"})
    assert token["access_token"] == "a" and token["refresh_token"] == "r2"
    args, kwargs = session.post.call_args
    assert args == (TOKEN_URL,) and "data" not in kwargs
    assert kwargs["json"] == {
        "grant_type": "refresh_token",
        "refresh_token": "r1",
        "client_id": "cid",
        "client_secret": "secret",
    }
