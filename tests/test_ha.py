"""Home Assistant level tests with a mocked Traccar client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.bus_monitor.const import DOMAIN, EVENT_ALERT
from custom_components.bus_monitor.models import Position
from custom_components.bus_monitor.traccar_client import CannotConnect, Device, InvalidAuth

CONN = {"base_url": "http://gps.example:8082", "username": "u", "password": "p"}
DEVICES = [Device(1, "Bus 12", "b12"), Device(2, "Bus 34", "b34")]


def _client(positions=None, login_exc=None):
    client = AsyncMock()
    client.login = AsyncMock(side_effect=login_exc)
    client.devices = AsyncMock(return_value=DEVICES)
    client.positions = AsyncMock(return_value=positions or [])
    return client


async def test_config_flow_happy_path(hass: HomeAssistant):
    with patch("custom_components.bus_monitor.config_flow.TraccarClient", return_value=_client()):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CONN)
        assert result["step_id"] == "devices"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"devices": ["1"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["devices"] == [1]


async def test_config_flow_errors(hass: HomeAssistant):
    for exc, key in ((InvalidAuth, "invalid_auth"), (CannotConnect, "cannot_connect")):
        with patch(
            "custom_components.bus_monitor.config_flow.TraccarClient",
            return_value=_client(login_exc=exc),
        ):
            result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
            result = await hass.config_entries.flow.async_configure(result["flow_id"], CONN)
        assert result["errors"] == {"base": key}


PROFILE = {
    "device_id": 1,
    "name": "Morning",
    "stop": {"lat": 40.0, "lon": -75.0, "radius_m": 75, "expected_arrival": None, "late_grace_min": 5},
    "checkpoints": [{"label": "5 min", "minutes": 5, "lat": 39.990, "lon": -75.0, "radius_m": 100, "announce": True}],
    "active_start": "00:00",
    "active_end": "23:59",
    "weekdays": [0, 1, 2, 3, 4, 5, 6],
}


async def _setup(hass, client):
    entry = MockConfigEntry(
        domain=DOMAIN, data={**CONN, "devices": [1]}, options={"profiles": {"morning": PROFILE}}
    )
    entry.add_to_hass(hass)
    with patch("custom_components.bus_monitor.TraccarClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _pos(lat, at):
    return Position(1, lat, -75.0, at, speed_mps=5, course=0.0)


async def test_setup_creates_entities_and_fires_alert(hass: HomeAssistant):
    now = datetime.now(UTC)
    client = _client([_pos(39.980, now - timedelta(seconds=30))])
    entry = await _setup(hass, client)

    assert hass.states.get("device_tracker.bus_12") is not None
    assert hass.states.get("sensor.bus_12_morning_status").state == "en_route"

    events = []
    hass.bus.async_listen(EVENT_ALERT, events.append)
    client.positions.return_value = [_pos(39.9905, now)]
    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(seconds=30))
    await hass.async_block_till_done()

    assert [e.data["label"] for e in events] == ["5 min"]
    assert hass.states.get("sensor.bus_12_morning_status").state == "near"
    assert entry.runtime_data.last_alert["morning"].minutes == 5


async def test_suggest_service_without_data_returns_empty(hass: HomeAssistant):
    await _setup(hass, _client([_pos(39.98, datetime.now(UTC))]))
    resp = await hass.services.async_call(
        DOMAIN, "suggest_checkpoints", {"profile": "morning"}, blocking=True, return_response=True
    )
    assert resp["trips_recorded"] == 0 and resp["suggestions"] == []


async def test_geocoder_parses_caches_and_reports_errors(hass: HomeAssistant, aioclient_mock):
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.bus_monitor.geocoder import GeocodeError, OverpassGeocoder
    from tests.test_streets import OVERPASS

    aioclient_mock.post("https://overpass-api.de/api/interpreter", json=OVERPASS)
    geo = OverpassGeocoder(async_get_clientsession(hass))
    with patch("custom_components.bus_monitor.geocoder.MIN_INTERVAL_S", 0):
        first = await geo.ways_near(40.0015, -75.0)
        again = await geo.ways_near(40.0016, -75.0)  # same ~55 m cell -> cache
    assert len(first) == 4 and again is first
    assert aioclient_mock.call_count == 1

    aioclient_mock.clear_requests()
    aioclient_mock.post("https://overpass-api.de/api/interpreter", status=429)
    with patch("custom_components.bus_monitor.geocoder.MIN_INTERVAL_S", 0):
        try:
            await geo.ways_near(41.0, -75.0)
        except GeocodeError as err:
            assert "429" in str(err)
        else:
            raise AssertionError("expected GeocodeError")


async def test_describe_location_service_speaks_and_returns_text(hass: HomeAssistant):
    from custom_components.bus_monitor.streets import parse_overpass
    from tests.test_streets import OVERPASS

    now = datetime.now(UTC)
    entry = await _setup(hass, _client([Position(1, 40.0015, -75.0, now, speed_mps=8, course=0.0)]))
    entry.runtime_data.geocoder = AsyncMock()
    entry.runtime_data.geocoder.ways_near = AsyncMock(return_value=parse_overpass(OVERPASS))
    speak = async_mock_service(hass, "tts", "speak")

    resp = await hass.services.async_call(
        DOMAIN,
        "describe_location",
        {"profile": "morning", "tts_entity": "tts.test", "media_player_entity": ["media_player.kitchen"]},
        blocking=True,
        return_response=True,
    )
    assert resp["street"] == "Oak Ave"
    assert (resp["cross_street_behind"], resp["cross_street_ahead"]) == ("3rd St", "5th St")
    assert resp["text"].startswith("Morning is on Oak Avenue between 3rd Street and 5th Street")
    assert speak[0].data["message"] == resp["text"]
    assert speak[0].data["media_player_entity_id"] == ["media_player.kitchen"]


async def test_checkpoint_from_bus_position_keeps_map_radius(hass: HomeAssistant):
    now = datetime.now(UTC)
    client = _client([_pos(39.9871, now)])
    entry = await _setup(hass, client)

    with patch("custom_components.bus_monitor.TraccarClient", return_value=client):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "add_checkpoint"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                "profile": "morning",
                "label": "10 minutes away",
                "minutes": 10,
                "location": {"latitude": 1.0, "longitude": 2.0, "radius": 300},
                "use_bus_position": True,
                "announce": True,
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    cp = entry.options["profiles"]["morning"]["checkpoints"][-1]
    assert (cp["lat"], cp["lon"], cp["radius_m"]) == (39.9871, -75.0, 300)
