"""Config and options flows."""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping
from datetime import time
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow, selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession, async_get_clientsession
from homeassistant.util import slugify

from .const import (
    CONF_BASE_URL,
    CONF_DEVICES,
    CONF_PASSWORD,
    CONF_PROVIDER,
    CONF_USERNAME,
    DOMAIN,
    OPT_PROFILES,
    OPT_SCAN_INTERVAL,
    OPT_SHOW_PANEL,
    PROVIDER_BOUNCIE,
    PROVIDER_TRACCAR,
    SCAN_INTERVALS,
)
from .geocoder import GeocodeError
from .locator import async_street_name
from .models import KIND_STREET, KIND_TIME
from .providers import CannotConnect, Device, InvalidAuth
from .providers.bouncie import BouncieClient, FixedToken
from .providers.traccar import TraccarClient

WEEKDAY_OPTIONS = [
    selector.SelectOptionDict(value=str(i), label=n)
    for i, n in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
]


def _location_selector() -> selector.LocationSelector:
    return selector.LocationSelector(selector.LocationSelectorConfig(radius=True))


def _hhmm(value: str) -> str:
    return time.fromisoformat(value).isoformat(timespec="minutes")


class BusMonitorConfigFlow(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Connect one tracking-provider account: a Traccar server or a Bouncie login (OAuth)."""

    DOMAIN = DOMAIN
    VERSION = 2

    def __init__(self) -> None:
        super().__init__()
        self._conn: dict[str, Any] = {}
        self._devices: list[Device] = []
        self._title = "School bus tracker"

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(__name__)

    async def _async_connect(self, conn: Mapping[str, Any]) -> list[Device]:
        session = async_create_clientsession(self.hass, cookie_jar=aiohttp.CookieJar(unsafe=True))
        client = TraccarClient(
            session, conn[CONF_BASE_URL], conn[CONF_USERNAME], conn[CONF_PASSWORD]
        )
        await client.login()
        return await client.devices()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=[PROVIDER_TRACCAR, PROVIDER_BOUNCIE])

    async def async_step_traccar(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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
                    self._conn = {**user_input, CONF_PROVIDER: PROVIDER_TRACCAR}
                    await self.async_set_unique_id(
                        f"{user_input[CONF_BASE_URL]}|{user_input[CONF_USERNAME]}"
                    )
                    self._abort_if_unique_id_configured()
                    return await self.async_step_devices()
        return self.async_show_form(
            step_id="traccar",
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

    async def async_step_bouncie(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_pick_implementation()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Bouncie sign-in finished: identify the user, then let them pick vehicles."""
        client = BouncieClient(async_get_clientsession(self.hass), FixedToken(data["token"]))
        try:
            user = await client.user()
            devices = await client.devices()
        except InvalidAuth:
            return self.async_abort(reason="invalid_auth")
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")
        await self.async_set_unique_id(f"{PROVIDER_BOUNCIE}|{user['id']}")
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=data)
        self._abort_if_unique_id_configured()
        if not devices:
            return self.async_abort(reason="no_devices")
        self._devices = devices
        self._conn = {**data, CONF_PROVIDER: PROVIDER_BOUNCIE}
        self._title = f"Bouncie ({user.get('name') or user.get('email') or user['id']})"
        return await self.async_step_devices()

    async def async_step_devices(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=self._title,
                data={**self._conn, CONF_DEVICES: [str(i) for i in user_input[CONF_DEVICES]]},
            )
        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICES): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            multiple=True,
                            options=[
                                selector.SelectOptionDict(value=d.id, label=d.name)
                                for d in sorted(self._devices, key=lambda d: d.name)
                            ],
                        )
                    )
                }
            ),
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        if entry_data.get(CONF_PROVIDER) == PROVIDER_BOUNCIE:
            return await self.async_step_reauth_bouncie()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_bouncie(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="reauth_bouncie")
        return await self.async_step_pick_implementation()

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
    """Add/edit/remove bus profiles and checkpoints."""

    _editing: str = ""  # profile id being edited

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
                value=i, label=coord.devices[i].name if coord and i in coord.devices else i
            )
            for i in map(str, self.config_entry.data[CONF_DEVICES])
        ]

    def _profile_options(self) -> list[selector.SelectOptionDict]:
        return [
            selector.SelectOptionDict(value=pid, label=p.get("name", pid))
            for pid, p in self._profiles().items()
        ]

    def _bus_position(self, device_id: str) -> dict[str, float] | None:
        coord = getattr(self.config_entry, "runtime_data", None)
        pos = coord.data.get(device_id) if coord and coord.data else None
        return {"latitude": pos.lat, "longitude": pos.lon} if pos else None

    async def _street_name(self, lat: float, lon: float) -> str:
        """Nearest cross street for a street checkpoint, or "" if the lookup fails."""
        try:
            return (await async_street_name(self.hass, lat, lon, None)).get("name") or ""
        except GeocodeError:
            return ""

    def _resolve_location(self, user_input: dict[str, Any], device_id: str) -> dict[str, Any] | None:
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
            menu_options=["add_profile", "edit_profile", "add_checkpoint", "remove", "settings"],
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
        default, minimum = SCAN_INTERVALS[
            self.config_entry.data.get(CONF_PROVIDER, PROVIDER_TRACCAR)
        ]
        current = self.config_entry.options.get(OPT_SCAN_INTERVAL, default)
        show_panel = self.config_entry.options.get(OPT_SHOW_PANEL, True)
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(OPT_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int), vol.Range(min=minimum, max=300)
                    ),
                    vol.Required(OPT_SHOW_PANEL, default=show_panel): bool,
                }
            ),
        )

    def _profile_schema(self) -> vol.Schema:
        """The bus profile form, shared by "add" and "edit"."""
        return vol.Schema(
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
        )

    @staticmethod
    def _profile_fields(user_input: dict[str, Any], loc: dict[str, Any]) -> dict[str, Any]:
        """Stored profile settings from the form (checkpoints are kept separately)."""
        expected = user_input.get("expected_arrival")
        return {
            "device_id": str(user_input["device"]),
            "name": user_input["name"],
            "stop": {
                "lat": loc["latitude"],
                "lon": loc["longitude"],
                "radius_m": loc.get("radius", 75),
                "expected_arrival": _hhmm(expected) if expected else None,
                "late_grace_min": int(user_input["late_grace_min"]),
            },
            "active_start": _hhmm(user_input["active_start"]),
            "active_end": _hhmm(user_input["active_end"]),
            "weekdays": [int(d) for d in user_input["weekdays"]],
            "offline_after_min": int(user_input["offline_after_min"]),
        }

    async def async_step_add_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            loc = self._resolve_location(user_input, str(user_input["device"]))
            if not loc:
                errors["base"] = "location_required"
            else:
                profiles = self._profiles()
                pid = slugify(user_input["name"])
                if pid in profiles:
                    errors["name"] = "name_exists"
                else:
                    profiles[pid] = {**self._profile_fields(user_input, loc), "checkpoints": []}
                    return self._save(profiles)
        return self.async_show_form(
            step_id="add_profile", errors=errors, data_schema=self._profile_schema()
        )

    async def async_step_edit_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the profile to change."""
        if not self._profiles():
            return self.async_abort(reason="no_profiles")
        if user_input is not None:
            self._editing = user_input["profile"]
            return await self.async_step_edit_profile_details()
        return self.async_show_form(
            step_id="edit_profile",
            data_schema=vol.Schema(
                {
                    vol.Required("profile"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=self._profile_options())
                    )
                }
            ),
        )

    async def async_step_edit_profile_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change a profile's name, bus, stop or schedule. Its id stays the same, so recorded
        trips, checkpoints, entities and scripts that use `profile: <id>` keep working."""
        errors: dict[str, str] = {}
        profiles = self._profiles()
        pid = self._editing
        current = profiles[pid]
        if user_input is not None:
            loc = self._resolve_location(user_input, str(user_input["device"]))
            taken = {
                key
                for other, p in profiles.items()
                if other != pid
                for key in (other, slugify(p.get("name", other)))
            }
            if not loc:
                errors["base"] = "location_required"
            elif slugify(user_input["name"]) in taken:
                errors["name"] = "name_exists"
            else:
                fields = self._profile_fields(user_input, loc)
                fields["stop"] = {**(current.get("stop") or {}), **fields["stop"]}
                profiles[pid] = {**current, **fields}
                return self._save(profiles)
        stop = current.get("stop") or {}
        suggested: dict[str, Any] = {
            "name": current.get("name", pid),
            "device": str(current["device_id"]),
            "late_grace_min": stop.get("late_grace_min", 10),
            "active_start": current.get("active_start", "05:30"),
            "active_end": current.get("active_end", "09:30"),
            "weekdays": [str(d) for d in current.get("weekdays", [0, 1, 2, 3, 4])],
            "offline_after_min": current.get("offline_after_min", 0),
        }
        if stop:
            suggested["location"] = {
                "latitude": stop["lat"],
                "longitude": stop["lon"],
                "radius": stop.get("radius_m", 75),
            }
        if stop.get("expected_arrival"):
            suggested["expected_arrival"] = stop["expected_arrival"]
        return self.async_show_form(
            step_id="edit_profile_details",
            errors=errors,
            data_schema=self.add_suggested_values_to_schema(
                self._profile_schema(), user_input or suggested
            ),
            description_placeholders={"profile_id": pid},
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
            street = user_input.get("kind") == KIND_STREET
            label = (user_input.get("label") or "").strip()
            if loc and not label:
                label = (
                    await self._street_name(loc["latitude"], loc["longitude"])
                    if street
                    else f"{int(user_input['minutes'])} minutes away"
                )
            if not loc:
                errors["base"] = "location_required"
            elif not label:
                errors["base"] = "street_lookup_failed"
            elif any(c["label"] == label for c in profile["checkpoints"]):
                errors["label"] = "name_exists"
            else:
                profile["checkpoints"] = [
                    *profile["checkpoints"],
                    {
                        "label": label,
                        "minutes": 0 if street else int(user_input["minutes"]),
                        "lat": loc["latitude"],
                        "lon": loc["longitude"],
                        "radius_m": loc.get("radius", 60 if street else 150),
                        "announce": bool(user_input["announce"]),
                        "kind": KIND_STREET if street else KIND_TIME,
                        "auto_place": bool(user_input.get("auto_place")) and not street,
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
                    vol.Required("kind", default=KIND_TIME): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value=KIND_TIME, label="Minutes away"),
                                selector.SelectOptionDict(value=KIND_STREET, label="Street (announce the cross street)"),
                            ]
                        )
                    ),
                    vol.Optional("label", default=""): str,
                    vol.Required("minutes", default=10): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=90)
                    ),
                    vol.Optional("location"): _location_selector(),
                    vol.Optional("use_bus_position", default=False): bool,
                    vol.Required("auto_place", default=True): bool,
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
