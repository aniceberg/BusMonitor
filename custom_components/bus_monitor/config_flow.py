"""Config and options flows."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import time
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.util import slugify

from .const import (
    CONF_BASE_URL,
    CONF_DEVICES,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    OPT_PROFILES,
    OPT_SCAN_INTERVAL,
    OPT_SHOW_PANEL,
)
from .traccar_client import CannotConnect, Device, InvalidAuth, TraccarClient

WEEKDAY_OPTIONS = [
    selector.SelectOptionDict(value=str(i), label=n)
    for i, n in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
]


def _location_selector() -> selector.LocationSelector:
    return selector.LocationSelector(selector.LocationSelectorConfig(radius=True))


def _hhmm(value: str) -> str:
    return time.fromisoformat(value).isoformat(timespec="minutes")


class BusMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._conn: dict[str, Any] = {}
        self._devices: list[Device] = []

    async def _async_connect(self, conn: Mapping[str, Any]) -> list[Device]:
        session = async_create_clientsession(self.hass, cookie_jar=aiohttp.CookieJar(unsafe=True))
        client = TraccarClient(
            session, conn[CONF_BASE_URL], conn[CONF_USERNAME], conn[CONF_PASSWORD]
        )
        await client.login()
        return await client.devices()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_BASE_URL] = user_input[CONF_BASE_URL].rstrip("/")
            try:
                self._devices = await self._async_connect(user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                if not self._devices:
                    errors["base"] = "no_devices"
                else:
                    self._conn = user_input
                    await self.async_set_unique_id(
                        f"{user_input[CONF_BASE_URL]}|{user_input[CONF_USERNAME]}"
                    )
                    self._abort_if_unique_id_configured()
                    return await self.async_step_devices()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BASE_URL): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                    ),
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_devices(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="School bus tracker",
                data={**self._conn, CONF_DEVICES: [int(i) for i in user_input[CONF_DEVICES]]},
            )
        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICES): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            multiple=True,
                            options=[
                                selector.SelectOptionDict(value=str(d.id), label=d.name)
                                for d in sorted(self._devices, key=lambda d: d.name)
                            ],
                        )
                    )
                }
            ),
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            conn = {**entry.data, **user_input}
            try:
                await self._async_connect(conn)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BusMonitorOptionsFlow()


class BusMonitorOptionsFlow(OptionsFlow):
    """Add/remove bus profiles and checkpoints."""

    def _profiles(self) -> dict[str, Any]:
        # Deep copy: editing the stored options in place makes Home Assistant see
        # "no change", so it would neither save nor reload the entry.
        return copy.deepcopy(dict(self.config_entry.options.get(OPT_PROFILES) or {}))

    def _save(self, profiles: dict[str, Any], **extra: Any) -> ConfigFlowResult:
        return self.async_create_entry(
            data={**self.config_entry.options, OPT_PROFILES: profiles, **extra}
        )

    def _device_options(self) -> list[selector.SelectOptionDict]:
        coord = getattr(self.config_entry, "runtime_data", None)
        return [
            selector.SelectOptionDict(
                value=str(i), label=coord.devices[i].name if coord and i in coord.devices else str(i)
            )
            for i in self.config_entry.data[CONF_DEVICES]
        ]

    def _profile_options(self) -> list[selector.SelectOptionDict]:
        return [
            selector.SelectOptionDict(value=pid, label=p.get("name", pid))
            for pid, p in self._profiles().items()
        ]

    def _bus_position(self, device_id: int) -> dict[str, float] | None:
        coord = getattr(self.config_entry, "runtime_data", None)
        pos = coord.data.get(device_id) if coord and coord.data else None
        return {"latitude": pos.lat, "longitude": pos.lon} if pos else None

    def _resolve_location(self, user_input: dict[str, Any], device_id: int) -> dict[str, Any] | None:
        """Map pick, or the bus's position if requested; the map's radius is kept either way."""
        loc = user_input.get("location")
        if user_input.get("use_bus_position") and (bus := self._bus_position(device_id)):
            if loc and "radius" in loc:
                bus["radius"] = loc["radius"]
            return bus
        return loc

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_profile", "add_checkpoint", "remove", "settings"],
        )

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self._save(
                self._profiles(),
                **{
                    OPT_SCAN_INTERVAL: int(user_input[OPT_SCAN_INTERVAL]),
                    OPT_SHOW_PANEL: bool(user_input[OPT_SHOW_PANEL]),
                },
            )
        current = self.config_entry.options.get(OPT_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        show_panel = self.config_entry.options.get(OPT_SHOW_PANEL, True)
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(OPT_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=300)
                    ),
                    vol.Required(OPT_SHOW_PANEL, default=show_panel): bool,
                }
            ),
        )

    async def async_step_add_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            device_id = int(user_input["device"])
            loc = self._resolve_location(user_input, device_id)
            if not loc:
                errors["base"] = "location_required"
            else:
                profiles = self._profiles()
                pid = slugify(user_input["name"])
                if pid in profiles:
                    errors["name"] = "name_exists"
                else:
                    expected = user_input.get("expected_arrival")
                    profiles[pid] = {
                        "device_id": device_id,
                        "name": user_input["name"],
                        "stop": {
                            "lat": loc["latitude"],
                            "lon": loc["longitude"],
                            "radius_m": loc.get("radius", 75),
                            "expected_arrival": _hhmm(expected) if expected else None,
                            "late_grace_min": int(user_input["late_grace_min"]),
                        },
                        "checkpoints": [],
                        "active_start": _hhmm(user_input["active_start"]),
                        "active_end": _hhmm(user_input["active_end"]),
                        "weekdays": [int(d) for d in user_input["weekdays"]],
                        "offline_after_min": int(user_input["offline_after_min"]),
                    }
                    return self._save(profiles)
        return self.async_show_form(
            step_id="add_profile",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required("name"): str,
                    vol.Required("device"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=self._device_options())
                    ),
                    vol.Optional("location"): _location_selector(),
                    vol.Optional("use_bus_position", default=False): bool,
                    vol.Optional("expected_arrival"): selector.TimeSelector(),
                    vol.Required("late_grace_min", default=10): vol.All(
                        vol.Coerce(int), vol.Range(min=0, max=60)
                    ),
                    vol.Required("active_start", default="05:30:00"): selector.TimeSelector(),
                    vol.Required("active_end", default="09:30:00"): selector.TimeSelector(),
                    vol.Required("weekdays", default=["0", "1", "2", "3", "4"]): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=WEEKDAY_OPTIONS, multiple=True)
                    ),
                    vol.Required("offline_after_min", default=0): vol.All(
                        vol.Coerce(int), vol.Range(min=0, max=120)
                    ),
                }
            ),
        )

    async def async_step_add_checkpoint(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        profiles = self._profiles()
        if not profiles:
            return self.async_abort(reason="no_profiles")
        if user_input is not None:
            profile = profiles[user_input["profile"]]
            loc = self._resolve_location(user_input, profile["device_id"])
            if not loc:
                errors["base"] = "location_required"
            elif any(c["label"] == user_input["label"] for c in profile["checkpoints"]):
                errors["label"] = "name_exists"
            else:
                profile["checkpoints"] = [
                    *profile["checkpoints"],
                    {
                        "label": user_input["label"],
                        "minutes": int(user_input["minutes"]),
                        "lat": loc["latitude"],
                        "lon": loc["longitude"],
                        "radius_m": loc.get("radius", 150),
                        "announce": bool(user_input["announce"]),
                    },
                ]
                return self._save(profiles)
        return self.async_show_form(
            step_id="add_checkpoint",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required("profile"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=self._profile_options())
                    ),
                    vol.Required("label", default="10 minutes away"): str,
                    vol.Required("minutes", default=10): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=90)
                    ),
                    vol.Optional("location"): _location_selector(),
                    vol.Optional("use_bus_position", default=False): bool,
                    vol.Required("announce", default=True): bool,
                }
            ),
        )

    async def async_step_remove(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        profiles = self._profiles()
        if not profiles:
            return self.async_abort(reason="no_profiles")
        if user_input is not None:
            pid = user_input["profile"]
            if user_input["delete_profile"]:
                profiles.pop(pid, None)
            else:
                drop = set(user_input.get("checkpoints", []))
                profiles[pid]["checkpoints"] = [
                    c for c in profiles[pid]["checkpoints"] if c["label"] not in drop
                ]
            return self._save(profiles)
        labels = sorted({c["label"] for p in profiles.values() for c in p["checkpoints"]})
        return self.async_show_form(
            step_id="remove",
            data_schema=vol.Schema(
                {
                    vol.Required("profile"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=self._profile_options())
                    ),
                    vol.Optional("checkpoints", default=[]): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=labels, multiple=True, custom_value=True)
                    ),
                    vol.Required("delete_profile", default=False): bool,
                }
            ),
        )
