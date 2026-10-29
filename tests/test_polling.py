"""The provider is only polled while a profile is watching (in its window, bus not arrived)."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.bus_monitor.alerts import TripTracker
from custom_components.bus_monitor.const import DOMAIN
from custom_components.bus_monitor.geocoder import GeocodeError
from custom_components.bus_monitor.models import Position

from .conftest import MONDAY_7AM, STOP_LAT, make_config, pos
from .test_ha import DATA, PROFILE, _client

NEVER = {**PROFILE, "weekdays": []}  # a profile whose watch window never opens


async def _setup(hass, client, profile=PROFILE):
    entry = MockConfigEntry(
        domain=DOMAIN, version=2, data=DATA, options={"profiles": {"morning": profile}}
    )
    entry.add_to_hass(hass)
    with patch("custom_components.bus_monitor.TraccarClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def _tick(hass, seconds=30):
    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(seconds=seconds))
    await hass.async_block_till_done()


def test_wants_position_only_in_window_until_arrival():
    tracker = TripTracker(make_config(active_start=time(6, 30), active_end=time(8, 0)))
    assert not tracker.wants_position(MONDAY_7AM.replace(hour=6))
    assert tracker.wants_position(MONDAY_7AM)
    assert not tracker.wants_position(MONDAY_7AM.replace(hour=9))
    assert not tracker.wants_position(MONDAY_7AM + timedelta(days=5))  # Saturday

    tracker.update(pos(39.95, at=MONDAY_7AM), MONDAY_7AM)  # seeds
    tracker.update(pos(STOP_LAT, at=MONDAY_7AM + timedelta(minutes=1)), MONDAY_7AM)
    assert tracker.arrived and not tracker.wants_position(MONDAY_7AM + timedelta(minutes=2))
    # next day the bus is watched again
    assert tracker.wants_position(MONDAY_7AM + timedelta(days=1))


async def test_no_polling_outside_the_watch_window(hass: HomeAssistant):
    client = _client([Position("1", 39.98, -75.0, datetime.now(UTC))])
    await _setup(hass, client, NEVER)
    # one fetch at startup so the map and tracker have a position
    assert client.positions.await_count == 1
    assert hass.states.get("device_tracker.bus_12").state != "unavailable"
    for _ in range(3):
        await _tick(hass)
    assert client.positions.await_count == 1


async def test_polling_stops_once_the_bus_has_arrived(hass: HomeAssistant):
    now = datetime.now(UTC)
    client = _client([Position("1", 39.98, -75.0, now - timedelta(seconds=30), speed_mps=5, course=0.0)])
    entry = await _setup(hass, client)
    await _tick(hass)
    polls = client.positions.await_count

    client.positions.return_value = [Position("1", 40.0, -75.0, now, speed_mps=0)]
    await _tick(hass, 60)
    assert entry.runtime_data.trackers["morning"].arrived
    assert client.positions.await_count == polls + 1

    for i in range(3):
        await _tick(hass, 90 + 30 * i)
    assert client.positions.await_count == polls + 1


async def test_where_is_the_bus_fetches_when_not_polling(hass: HomeAssistant):
    now = datetime.now(UTC)
    client = _client([Position("1", 39.98, -75.0, now - timedelta(hours=3))])
    entry = await _setup(hass, client, NEVER)
    entry.runtime_data.geocoder = AsyncMock()
    entry.runtime_data.geocoder.ways_near = AsyncMock(side_effect=GeocodeError("offline"))

    client.positions.return_value = [Position("1", 39.99, -75.0, now)]
    resp = await hass.services.async_call(
        DOMAIN, "describe_location", {"profile": "morning"}, blocking=True, return_response=True
    )
    assert client.positions.await_count == 2
    assert resp["latitude"] == 39.99 and "last reported" not in resp["text"]
