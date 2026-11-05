"""Following device_tracker entities that other integrations made."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bus_monitor.const import DOMAIN
from custom_components.bus_monitor.providers.ha_tracker import HomeAssistantTrackers

BUS = "device_tracker.bus_12"
GPS = {"latitude": 40.0, "longitude": -75.0, "friendly_name": "Bus 12", "source_type": "gps"}
ROUTER = {"source_type": "router", "friendly_name": "Router phone"}


async def _start_flow(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "device_tracker"}
    )


async def test_only_trackers_with_a_location_are_offered(hass: HomeAssistant):
    hass.states.async_set(BUS, "not_home", GPS)
    hass.states.async_set("device_tracker.router_phone", "home", ROUTER)
    registry = er.async_get(hass)
    registry.async_get_or_create("device_tracker", DOMAIN, "own", suggested_object_id="own")
    hass.states.async_set("device_tracker.own", "not_home", GPS)

    result = await _start_flow(hass)

    assert result["step_id"] == "devices"
    options = result["data_schema"].schema["devices"].config["options"]
    assert options == [{"value": BUS, "label": "Bus 12"}]


async def test_flow_creates_entry_and_leads_into_the_first_profile(hass: HomeAssistant):
    hass.states.async_set(BUS, "not_home", GPS)
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"devices": [BUS]})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home Assistant trackers"
    assert result["data"] == {"provider": "device_tracker", "devices": [BUS]}
    assert "next_flow" in result
    assert result["result"].state is ConfigEntryState.LOADED
    assert result["result"].runtime_data.data[BUS].lat == 40.0


async def test_flow_explains_when_no_tracker_has_a_location(hass: HomeAssistant):
    hass.states.async_set("device_tracker.router_phone", "home", ROUTER)
    result = await _start_flow(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_trackers"


async def test_provider_is_only_added_once(hass: HomeAssistant):
    hass.states.async_set(BUS, "not_home", GPS)
    MockConfigEntry(domain=DOMAIN, version=2, minor_version=3, unique_id="device_tracker").add_to_hass(hass)
    result = await _start_flow(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_speed_and_course_come_from_movement(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
):
    provider = HomeAssistantTrackers(hass)
    hass.states.async_set(BUS, "not_home", {**GPS, "speed": 999})
    first = (await provider.positions())[0]
    assert first.speed_mps == 0.0
    assert first.course is None

    freezer.tick(timedelta(seconds=10))
    # about 111 m due north in 10 s
    hass.states.async_set(BUS, "not_home", {**GPS, "latitude": 40.001, "speed": 999})
    moved = (await provider.positions())[0]
    assert 10 < moved.speed_mps < 12
    assert moved.course == 0.0
    assert moved.fix_time > first.fix_time

    # Still the same fix: no new information, so it keeps its motion...
    freezer.tick(timedelta(seconds=10))
    assert (await provider.positions())[0].speed_mps == moved.speed_mps

    # ...until the tracker has gone quiet for a while.
    freezer.tick(timedelta(minutes=3))
    assert (await provider.positions())[0].speed_mps == 0.0


async def test_new_report_from_the_same_place_means_stopped(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
):
    provider = HomeAssistantTrackers(hass)
    hass.states.async_set(BUS, "not_home", GPS)
    await provider.positions()
    freezer.tick(timedelta(seconds=10))
    hass.states.async_set(BUS, "not_home", {**GPS, "latitude": 40.001})
    await provider.positions()
    freezer.tick(timedelta(seconds=10))
    hass.states.async_set(BUS, "not_home", {**GPS, "latitude": 40.001, "battery_level": 50})
    stopped = (await provider.positions())[0]
    assert stopped.speed_mps == 0.0
    assert stopped.course == 0.0  # the last direction is still the best guess


async def test_inaccurate_or_missing_locations(hass: HomeAssistant):
    provider = HomeAssistantTrackers(hass)
    hass.states.async_set(BUS, "not_home", {**GPS, "gps_accuracy": 1500})
    assert (await provider.positions())[0].valid is False
    hass.states.async_set(BUS, "not_home", {**GPS, "gps_accuracy": 20})
    assert (await provider.positions())[0].valid is True
    hass.states.async_set(BUS, "unavailable", GPS)
    assert await provider.positions() == []
    hass.states.async_set(BUS, "not_home", {**GPS, "latitude": "nowhere"})
    assert await provider.positions() == []


async def test_tracker_not_loaded_yet_keeps_its_name(hass: HomeAssistant):
    """After a restart the bus integration may load later than Bus Monitor."""
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "device_tracker", "other", "bus", suggested_object_id="bus_12", original_name="Bus 12"
    )
    provider = HomeAssistantTrackers(hass)
    devices = {d.id: d for d in await provider.devices()}
    assert devices[entry.entity_id].name == "Bus 12"
    assert devices[entry.entity_id].status is None
    assert await provider.positions() == []


def _entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        minor_version=3,
        title="Home Assistant trackers",
        unique_id="device_tracker",
        data={"provider": "device_tracker", "devices": [BUS]},
        subentries_data=[
            ConfigSubentryData(
                subentry_type="bus_profile",
                title="Morning",
                unique_id="morning",
                data={
                    "profile_id": "morning",
                    "name": "Morning",
                    "device_id": BUS,
                    "stop": {"lat": 40.01, "lon": -75.0, "radius_m": 75},
                    "checkpoints": [],
                    "active_start": "00:00",
                    "active_end": "23:59",
                    "weekdays": [0, 1, 2, 3, 4, 5, 6],
                    "season_end": "2099-06-30",
                },
            )
        ],
    )
    entry.add_to_hass(hass)
    return entry


async def test_profile_follows_the_tracker_and_survives_it_loading_late(hass: HomeAssistant):
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    coordinator = entry.runtime_data
    assert coordinator.data == {}

    # The tracker's integration has now loaded.
    hass.states.async_set(BUS, "not_home", GPS)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success
    assert coordinator.data[BUS].lat == 40.0

    # Bus Monitor's mirror of the bus must never be picked up as a tracker of its own.
    ids = {d.id for d in await HomeAssistantTrackers(hass).devices()}
    assert ids == {BUS}
