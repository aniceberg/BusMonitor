"""Bus Monitor: school-bus arrival alerts from a Traccar GPS server."""

from __future__ import annotations

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession, async_get_clientsession
from homeassistant.helpers.storage import Store

from .calibration import checkpoint_stats, suggest_checkpoints
from .const import (
    CONF_BASE_URL,
    CONF_DEVICES,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    SERVICE_DESCRIBE,
    SERVICE_RESET_TRIP,
    SERVICE_SUGGEST,
    STREETS_STORAGE_KEY,
    STREETS_STORAGE_VERSION,
)
from .coordinator import BusMonitorCoordinator
from .geocoder import OverpassGeocoder
from .locator import async_describe
from .panel import async_setup_frontend, async_update_panel
from .traccar_client import CannotConnect, InvalidAuth, TraccarClient
from .websocket import async_register_websocket

PLATFORMS = [Platform.DEVICE_TRACKER, Platform.SENSOR, Platform.BINARY_SENSOR]

type BusMonitorConfigEntry = ConfigEntry[BusMonitorCoordinator]

RESET_SCHEMA = vol.Schema({vol.Required("profile"): cv.string})
SUGGEST_SCHEMA = vol.Schema(
    {
        vol.Required("profile"): cv.string,
        vol.Optional("minutes", default=[10, 5, 2]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    }
)
DESCRIBE_SCHEMA = vol.Schema(
    {
        vol.Required("profile"): cv.string,
        vol.Optional("tts_entity"): cv.entity_id,
        vol.Optional("media_player_entity"): cv.entity_ids,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: BusMonitorConfigEntry) -> bool:
    # Dedicated session: Traccar uses a session cookie that must not leak into
    # Home Assistant's shared aiohttp session.
    session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar(unsafe=True))
    client = TraccarClient(
        session,
        entry.data[CONF_BASE_URL],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    try:
        await client.login()
        devices = {d.id: d for d in await client.devices()}
    except InvalidAuth as err:
        raise ConfigEntryAuthFailed from err
    except CannotConnect as err:
        raise ConfigEntryNotReady(str(err)) from err

    device_ids = [int(i) for i in entry.data[CONF_DEVICES]]
    coordinator = BusMonitorCoordinator(hass, entry, client, device_ids, devices)
    coordinator.geocoder = await _async_geocoder(hass)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_websocket(hass)
    await async_setup_frontend(hass)
    await async_update_panel(hass, setting_up=entry)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    _register_services(hass)
    return True


async def _async_geocoder(hass: HomeAssistant) -> OverpassGeocoder:
    """One shared street lookup with a cache that survives restarts."""
    data = hass.data.setdefault(DOMAIN, {})
    if (geocoder := data.get("geocoder")) is None:
        store: Store = Store(hass, STREETS_STORAGE_VERSION, STREETS_STORAGE_KEY)
        cache = await store.async_load()

        def _schedule_save() -> None:
            store.async_delay_save(lambda: geocoder.cache, 30)

        geocoder = OverpassGeocoder(async_get_clientsession(hass), cache=cache, on_change=_schedule_save)
        data["geocoder"] = geocoder
    return geocoder


async def async_unload_entry(hass: HomeAssistant, entry: BusMonitorConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await async_update_panel(hass, unloading=entry)
        await entry.runtime_data.store.async_save(entry.runtime_data.data_to_save())
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: BusMonitorConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _find(hass: HomeAssistant, profile: str) -> BusMonitorCoordinator:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        if profile in entry.runtime_data.trackers:
            return entry.runtime_data
    raise ServiceValidationError(f"Unknown bus profile '{profile}'")


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_RESET_TRIP):
        return

    async def reset_trip(call: ServiceCall) -> None:
        _find(hass, call.data["profile"]).reset_trip(call.data["profile"])

    async def suggest(call: ServiceCall) -> dict:
        profile = call.data["profile"]
        coord = _find(hass, profile)
        trips = coord.recorder.trips_for(profile)
        cfg = coord.trackers[profile].config
        return {
            "trips_recorded": len(trips),
            "suggestions": suggest_checkpoints(trips, call.data["minutes"]),
            "current_checkpoints": [
                {**c.as_dict(), "actual_minutes_to_stop": checkpoint_stats(trips, c.label)}
                for c in cfg.checkpoints
            ],
        }

    async def describe(call: ServiceCall) -> dict:
        profile = call.data["profile"]
        result = await async_describe(hass, _find(hass, profile), profile)
        if call.data.get("tts_entity") and call.data.get("media_player_entity"):
            await hass.services.async_call(
                "tts",
                "speak",
                {
                    "entity_id": call.data["tts_entity"],
                    "media_player_entity_id": call.data["media_player_entity"],
                    "message": result["text"],
                },
                blocking=True,
                context=call.context,
            )
        return result

    hass.services.async_register(
        DOMAIN,
        SERVICE_DESCRIBE,
        describe,
        schema=DESCRIBE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, SERVICE_RESET_TRIP, reset_trip, schema=RESET_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_SUGGEST,
        suggest,
        schema=SUGGEST_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
