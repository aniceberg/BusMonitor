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

    from custom_components.bus_monitor.geocoder import OVERPASS_URLS, GeocodeError, OverpassGeocoder
    from tests.test_streets import OVERPASS

    aioclient_mock.post("https://overpass-api.de/api/interpreter", json=OVERPASS)
    geo = OverpassGeocoder(async_get_clientsession(hass))
    with patch("custom_components.bus_monitor.geocoder.MIN_INTERVAL_S", 0):
        first = await geo.ways_near(40.0015, -75.0)
        again = await geo.ways_near(40.0016, -75.0)  # same cell -> cache
    assert len(first) == 4 and [w.name for w in again] == [w.name for w in first]
    assert aioclient_mock.call_count == 1

    aioclient_mock.clear_requests()
    for url in OVERPASS_URLS:
        aioclient_mock.post(url, status=429)
    with patch("custom_components.bus_monitor.geocoder.MIN_INTERVAL_S", 0):
        try:
            await geo.ways_near(41.0, -75.0)
        except GeocodeError as err:
            assert "HTTP 429" in str(err)
        else:
            raise AssertionError("expected GeocodeError")
        assert aioclient_mock.call_count == len(OVERPASS_URLS)  # every mirror tried
        # backing off: the next lookup fails fast without calling the servers
        try:
            await geo.ways_near(42.0, -75.0)
        except GeocodeError:
            pass
        assert aioclient_mock.call_count == len(OVERPASS_URLS)


async def test_geocoder_falls_back_to_mirror_and_cache_persists(hass: HomeAssistant, aioclient_mock):
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.bus_monitor.geocoder import OVERPASS_URLS, OverpassGeocoder
    from tests.test_streets import OVERPASS

    aioclient_mock.post(OVERPASS_URLS[0], status=502)
    aioclient_mock.post(OVERPASS_URLS[1], json=OVERPASS)
    saved = []
    geo = OverpassGeocoder(async_get_clientsession(hass), on_change=lambda: saved.append(1))
    with patch("custom_components.bus_monitor.geocoder.MIN_INTERVAL_S", 0):
        ways = await geo.ways_near(40.0015, -75.0)
    assert len(ways) == 4 and saved == [1]
    # a new geocoder built from the saved cache answers without any request
    aioclient_mock.clear_requests()
    again = await OverpassGeocoder(async_get_clientsession(hass), cache=geo.cache).ways_near(40.0012, -75.0004)
    assert sorted(w.name for w in again) == sorted(w.name for w in ways)
    assert aioclient_mock.call_count == 0


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
    assert resp["text"].startswith("Bus 12 is on Oak Avenue between 3rd Street and 5th Street")
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
    # The entry must have been saved and reloaded, so the running tracker sees it.
    tracker = entry.runtime_data.trackers["morning"]
    assert "10 minutes away" in [c.label for c in tracker.config.checkpoints]
    assert hass.states.get("sensor.bus_12_morning_10_minutes_away_actual_minutes") is not None


async def test_remove_checkpoint_is_saved(hass: HomeAssistant):
    client = _client([_pos(39.98, datetime.now(UTC))])
    entry = await _setup(hass, client)
    with patch("custom_components.bus_monitor.TraccarClient", return_value=client):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "remove"}
        )
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"profile": "morning", "checkpoints": ["5 min"], "delete_profile": False},
        )
        await hass.async_block_till_done()
    assert entry.runtime_data.trackers["morning"].config.checkpoints == ()


async def test_reload_while_bus_at_stop_does_not_repeat_arrival(hass: HomeAssistant):
    now = datetime.now(UTC)
    client = _client([Position(1, 40.0, -75.0, now, speed_mps=0, course=0.0)])
    events = []
    hass.bus.async_listen(EVENT_ALERT, events.append)
    entry = await _setup(hass, client)
    assert hass.states.get("sensor.bus_12_morning_status").state == "arrived"

    client.positions.return_value = [Position(1, 40.0, -75.0, now + timedelta(seconds=10), speed_mps=0)]
    with patch("custom_components.bus_monitor.TraccarClient", return_value=client):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert events == []


async def test_alert_event_names_the_bus(hass: HomeAssistant):
    now = datetime.now(UTC)
    client = _client([_pos(39.980, now - timedelta(seconds=30))])
    await _setup(hass, client)
    events = []
    hass.bus.async_listen(EVENT_ALERT, events.append)
    client.positions.return_value = [_pos(39.9905, now)]
    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(seconds=30))
    await hass.async_block_till_done()
    assert (events[0].data["bus"], events[0].data["profile_name"]) == ("Bus 12", "Morning")


async def test_panel_registered_and_websocket_api(hass: HomeAssistant, hass_ws_client):
    from homeassistant.components.frontend import DATA_PANELS

    from custom_components.bus_monitor.calibration import TripRecord

    now = datetime.now(UTC)
    entry = await _setup(hass, _client([_pos(39.98, now)]))
    assert "bus-monitor" in hass.data[DATA_PANELS]
    assert hass.data[DATA_PANELS]["bus-monitor"].sidebar_icon == "busmonitor:bus"

    trail = [(now + timedelta(seconds=15 * i), 39.98 + i * 0.0004, -75.0, 5.0) for i in range(10)]
    entry.runtime_data.recorder.trips.append(TripRecord("morning", "2026-10-19", trail[-1][0], {}, trail))

    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "bus_monitor/overview"})
    ov = (await ws.receive_json())["result"]
    prof = ov["profiles"][0]
    assert ov["can_edit"] and prof["id"] == "morning" and prof["bus"] == "Bus 12"
    assert prof["tracker_entity"] == "device_tracker.bus_12" and prof["trips"] == 1

    await ws.send_json({"id": 2, "type": "bus_monitor/route", "profile": "morning"})
    route = (await ws.receive_json())["result"]
    assert route["trips"] == 1 and len(route["latest"]["path"]) == 10
    assert route["heatmap"]["cells"] and all(c[2] == 1.0 for c in route["heatmap"]["cells"])

    new = [{"label": "10 min", "minutes": 10, "lat": 39.97, "lon": -75.0, "radius_m": 50, "announce": True}]
    with patch("custom_components.bus_monitor.TraccarClient", return_value=entry.runtime_data.client):
        await ws.send_json({"id": 3, "type": "bus_monitor/set_checkpoints", "profile": "morning", "checkpoints": new})
        assert (await ws.receive_json())["success"]
        await hass.async_block_till_done()
    assert [c.label for c in entry.runtime_data.trackers["morning"].config.checkpoints] == ["10 min"]

    dup = new + [dict(new[0])]
    await ws.send_json({"id": 4, "type": "bus_monitor/set_checkpoints", "profile": "morning", "checkpoints": dup})
    assert not (await ws.receive_json())["success"]


async def test_panel_can_be_hidden(hass: HomeAssistant):
    from homeassistant.components.frontend import DATA_PANELS

    client = _client([_pos(39.98, datetime.now(UTC))])
    entry = await _setup(hass, client)
    with patch("custom_components.bus_monitor.TraccarClient", return_value=client):
        hass.config_entries.async_update_entry(entry, options={**entry.options, "show_panel": False})
        await hass.async_block_till_done()
    assert "bus-monitor" not in hass.data[DATA_PANELS]


async def test_restart_after_arrival_does_not_announce_late(hass: HomeAssistant, hass_storage):
    """Reproduces the 'East 7th is late' announcement after a restart post-arrival."""
    from homeassistant.util import dt as dt_util

    local_now = dt_util.now()
    profile = {
        **PROFILE,
        "stop": {**PROFILE["stop"], "expected_arrival": (local_now - timedelta(minutes=30)).strftime("%H:%M")},
    }
    hass_storage["bus_monitor.trips.restart_test"] = {
        "version": 1,
        "key": "bus_monitor.trips.restart_test",
        "data": {
            "trips": [],
            "state": {
                "morning": {
                    "date": local_now.date().isoformat(),
                    "status": "arrived",
                    "fired": ["5 min"],
                    "crossings": {},
                    "arrival": (local_now - timedelta(minutes=25)).isoformat(),
                    "late_fired": False,
                    "offline_fired": False,
                }
            },
        },
    }
    entry = MockConfigEntry(
        domain=DOMAIN, entry_id="restart_test", data={**CONN, "devices": [1]}, options={"profiles": {"morning": profile}}
    )
    entry.add_to_hass(hass)
    events = []
    hass.bus.async_listen(EVENT_ALERT, events.append)
    # bus has left the stop and is driving away
    client = _client([Position(1, 39.98, -75.0, datetime.now(UTC), speed_mps=8, course=180.0)])
    with patch("custom_components.bus_monitor.TraccarClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(seconds=30))
    await hass.async_block_till_done()
    assert events == []
    assert hass.states.get("binary_sensor.bus_12_morning_running_late").state == "off"
    assert hass.states.get("sensor.bus_12_morning_status").state == "arrived"
