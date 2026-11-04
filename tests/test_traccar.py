"""Traccar client and pasted-address handling (REST mocked; no real server needed)."""

from __future__ import annotations

import pytest
from aiohttp import ClientConnectionError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

from custom_components.bus_monitor.providers.traccar import (
    CannotConnect,
    InvalidAuth,
    NotTraccar,
    TraccarClient,
    resolve_server,
    server_urls,
)

BASE = "http://gps.example:8082"


@pytest.fixture
def client(hass: HomeAssistant, aioclient_mock) -> TraccarClient:
    return TraccarClient(async_get_clientsession(hass), BASE, "parent@example.com", "pw")


@pytest.mark.parametrize(
    ("pasted", "expected"),
    [
        ("http://gps.example:8082", ["http://gps.example:8082"]),
        ("  https://GPS.example/  ", ["https://gps.example"]),
        ("HTTP://gps.example:8082/", ["http://gps.example:8082"]),
        ("http://gps.example:8082/login?next=1#/map", ["http://gps.example:8082"]),
        ("http://gps.example:8082/settings/devices", ["http://gps.example:8082"]),
        ("http://gps.example:8082/api/session", ["http://gps.example:8082"]),
        ("http://gps.example:8082/index.html", ["http://gps.example:8082"]),
        ("https://user:secret@gps.example", ["https://gps.example"]),
        ("https://example.com/traccar/login", ["https://example.com/traccar"]),
        ("gps.example:8082", ["https://gps.example:8082", "http://gps.example:8082"]),
        ("gps.example/", ["https://gps.example", "http://gps.example"]),
        ("192.0.2.7:8082/login", ["https://192.0.2.7:8082", "http://192.0.2.7:8082"]),
    ],
)
def test_server_urls_normalises_what_people_paste(pasted, expected):
    assert server_urls(pasted) == expected


@pytest.mark.parametrize(
    "pasted", ["", "   ", "not a url", "ftp://gps.example", "http://", "gps.example:port"]
)
def test_server_urls_rejects_what_cant_be_an_address(pasted):
    with pytest.raises(ValueError):
        server_urls(pasted)


async def test_resolve_keeps_a_named_scheme_without_probing(hass, aioclient_mock):
    session = async_get_clientsession(hass)
    assert await resolve_server(session, "http://gps.example:8082/login") == BASE
    assert aioclient_mock.call_count == 0


async def test_resolve_prefers_https(hass, aioclient_mock):
    aioclient_mock.get("https://gps.example:8082/api/server", status=404)
    session = async_get_clientsession(hass)
    assert await resolve_server(session, "gps.example:8082") == "https://gps.example:8082"
    assert aioclient_mock.call_count == 1


async def test_resolve_falls_back_to_http_without_sending_a_login(hass, aioclient_mock):
    aioclient_mock.get("https://gps.example:8082/api/server", exc=ClientConnectionError())
    aioclient_mock.get(f"{BASE}/api/server", json={"version": "4.1"})
    session = async_get_clientsession(hass)
    assert await resolve_server(session, "gps.example:8082") == BASE
    assert all(method == "GET" and data is None for method, _, data, _ in aioclient_mock.mock_calls)


async def test_resolve_reports_when_nothing_answers(hass, aioclient_mock):
    aioclient_mock.get("https://gps.example:8082/api/server", exc=TimeoutError())
    aioclient_mock.get(f"{BASE}/api/server", exc=ClientConnectionError())
    with pytest.raises(CannotConnect):
        await resolve_server(async_get_clientsession(hass), "gps.example:8082")


async def test_login_posts_credentials(client, aioclient_mock):
    aioclient_mock.post(f"{BASE}/api/session", json={"id": 1, "name": "Pat"})
    await client.login()
    assert aioclient_mock.mock_calls[0][2] == {"email": "parent@example.com", "password": "pw"}


@pytest.mark.parametrize("status", [401, 403])
async def test_login_rejected(client, aioclient_mock, status):
    aioclient_mock.post(f"{BASE}/api/session", status=status)
    with pytest.raises(InvalidAuth):
        await client.login()


@pytest.mark.parametrize(
    "response",
    [
        {"status": 404},
        {"status": 405},
        {"status": 200, "text": "<html>Welcome to my router</html>"},
        {"status": 200, "json": ["not", "a", "user"]},
    ],
)
async def test_login_to_something_else_is_not_traccar(client, aioclient_mock, response):
    aioclient_mock.post(f"{BASE}/api/session", **response)
    with pytest.raises(NotTraccar):
        await client.login()


@pytest.mark.parametrize(
    "response",
    [{"status": 500}, {"status": 502}, {"exc": ClientConnectionError()}, {"exc": TimeoutError()}],
)
async def test_login_when_the_server_is_down(client, aioclient_mock, response):
    aioclient_mock.post(f"{BASE}/api/session", **response)
    with pytest.raises(CannotConnect) as err:
        await client.login()
    assert not isinstance(err.value, NotTraccar)


async def test_devices_are_parsed(client, aioclient_mock):
    aioclient_mock.get(
        f"{BASE}/api/devices",
        json=[
            {"id": 7, "name": "Bus 12", "uniqueId": "b12", "status": "online"},
            {"id": 8},
        ],
    )
    first, second = await client.devices()
    assert (first.id, first.name, first.unique_id, first.status) == ("7", "Bus 12", "b12", "online")
    assert (second.id, second.name, second.unique_id, second.status) == ("8", "8", "", None)


async def test_expired_session_signs_in_again_and_retries_once(client, aioclient_mock):
    answers = iter([AiohttpClientMockResponse("GET", f"{BASE}/api/devices", status=401)])

    async def devices(method, url, data):
        return next(
            answers,
            AiohttpClientMockResponse("GET", url, json=[{"id": 7, "name": "Bus 12"}]),
        )

    aioclient_mock.get(f"{BASE}/api/devices", side_effect=devices)
    aioclient_mock.post(f"{BASE}/api/session", json={"id": 1})
    assert [d.name for d in await client.devices()] == ["Bus 12"]
    assert [call[0] for call in aioclient_mock.mock_calls] == ["GET", "POST", "GET"]


async def test_still_unauthorised_after_signing_in_again(client, aioclient_mock):
    aioclient_mock.get(f"{BASE}/api/devices", status=401)
    aioclient_mock.post(f"{BASE}/api/session", json={"id": 1})
    with pytest.raises(InvalidAuth):
        await client.devices()


@pytest.mark.parametrize(
    ("response", "error"),
    [
        ({"status": 500}, CannotConnect),
        ({"exc": ClientConnectionError()}, CannotConnect),
        ({"text": "<html>"}, NotTraccar),
        ({"json": {"not": "a list"}}, NotTraccar),
        ({"json": [{"name": "no id"}]}, NotTraccar),
        ({"json": ["not a device"]}, NotTraccar),
    ],
)
async def test_devices_failures(client, aioclient_mock, response, error):
    aioclient_mock.get(f"{BASE}/api/devices", **response)
    with pytest.raises(error):
        await client.devices()


async def test_positions_skip_malformed_items(client, aioclient_mock):
    good = {
        "deviceId": 7,
        "latitude": 40.0,
        "longitude": -75.0,
        "fixTime": "2026-10-12T07:00:00.000+00:00",
        "speed": 10.0,
        "course": 90.0,
        "valid": True,
    }
    aioclient_mock.get(f"{BASE}/api/positions", json=[good, {"deviceId": 8}, "junk"])
    positions = await client.positions()
    assert [(p.device_id, p.lat, p.lon) for p in positions] == [("7", 40.0, -75.0)]
