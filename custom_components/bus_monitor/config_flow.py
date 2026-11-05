"""Config and options flows."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date, time
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_USER,
    ConfigEntry,
    ConfigFlowResult,
    ConfigSubentryFlow,
    FlowType,
    OptionsFlow,
    SubentryFlowContext,
    SubentryFlowResult,
)
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow, selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession, async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import (
    CONF_BASE_URL,
    CONF_DEVICES,
    CONF_PASSWORD,
    CONF_PROFILE_ID,
    CONF_PROVIDER,
    CONF_USERNAME,
    DOMAIN,
    OPT_SCAN_INTERVAL,
    OPT_SHOW_PANEL,
    PROVIDER_BOUNCIE,
    PROVIDER_HA_TRACKER,
    PROVIDER_TRACCAR,
    SCAN_INTERVALS,
    SUBENTRY_PROFILE,
)
from .geocoder import GeocodeError
from .locator import async_street_name
from .models import KIND_STREET, KIND_TIME, default_season_end
from .profiles import profile_settings, taken_names
from .providers import CannotConnect, Device, InvalidAuth
from .providers.bouncie import BouncieClient, FixedToken
from .providers.ha_tracker import HomeAssistantTrackers
from .providers.traccar import NotTraccar, TraccarClient, resolve_server

BOUNCIE_PORTAL_URL = "https://www.bouncie.dev"
BLUEPRINT_IMPORT_URL = (
    "https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url="
    "https%3A%2F%2Fgithub.com%2Faniceberg%2FBusMonitor%2Fblob%2Fmain%2Fblueprints%2Fautomation"
    "%2Fbus_monitor%2Fannounce_bus_alerts.yaml"
)
GUIDE_URL = "https://github.com/aniceberg/BusMonitor/blob/main/docs/automations.md"

WEEKDAY_OPTIONS = [
    selector.SelectOptionDict(value=str(i), label=n)
    for i, n in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
]


def _location_selector() -> selector.LocationSelector:
    return selector.LocationSelector(selector.LocationSelectorConfig(radius=True))


def _hhmm(value: str) -> str:
    return time.fromisoformat(value).isoformat(timespec="minutes")


class BusMonitorConfigFlow(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Connect one position source: a Traccar server, a Bouncie login (OAuth) or the GPS
    trackers already in this Home Assistant."""

    DOMAIN = DOMAIN
    VERSION = 2
    MINOR_VERSION = 3

    def __init__(self) -> None:
        super().__init__()
        self._conn: dict[str, Any] = {}
        self._devices: list[Device] = []
        self._title = "School bus tracker"

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(__name__)

    def _session(self) -> aiohttp.ClientSession:
        return async_create_clientsession(self.hass, cookie_jar=aiohttp.CookieJar(unsafe=True))

    async def _async_connect(
        self, session: aiohttp.ClientSession, conn: Mapping[str, Any]
    ) -> list[Device]:
        client = TraccarClient(
            session, conn[CONF_BASE_URL], conn[CONF_USERNAME], conn[CONF_PASSWORD]
        )
        await client.login()
        return await client.devices()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user", menu_options=[PROVIDER_TRACCAR, PROVIDER_BOUNCIE, PROVIDER_HA_TRACKER]
        )

    async def async_step_traccar(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            session = self._session()
            try:
                base_url = await resolve_server(session, user_input[CONF_BASE_URL])
                conn = {**user_input, CONF_BASE_URL: base_url, CONF_USERNAME: username}
                self._devices = await self._async_connect(session, conn)
            except ValueError:
                errors[CONF_BASE_URL] = "invalid_url"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except NotTraccar:
                errors[CONF_BASE_URL] = "not_traccar"
            except CannotConnect:
                errors[CONF_BASE_URL] = "cannot_connect"
            else:
                if not self._devices:
                    errors["base"] = "no_devices"
                else:
                    self._conn = {**conn, CONF_PROVIDER: PROVIDER_TRACCAR}
                    await self.async_set_unique_id(f"{base_url}|{username}")
                    self._abort_if_unique_id_configured()
                    return await self.async_step_devices()
        schema = vol.Schema(
            {
                vol.Required(CONF_BASE_URL): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                ),
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(
            step_id="traccar",
            data_schema=self.add_suggested_values_to_schema(
                schema, {k: v for k, v in (user_input or {}).items() if k != CONF_PASSWORD}
            ),
            errors=errors,
        )

    async def async_step_bouncie(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Sign in to Bouncie; the first time, register the Bouncie app right here."""
        if user_input is not None:
            await async_import_client_credential(
                self.hass,
                DOMAIN,
                ClientCredential(
                    user_input[CONF_CLIENT_ID].strip(),
                    user_input[CONF_CLIENT_SECRET].strip(),
                    "Bouncie",
                ),
            )
        if await config_entry_oauth2_flow.async_get_implementations(self.hass, DOMAIN):
            return await self.async_step_pick_implementation()
        try:
            redirect_url = config_entry_oauth2_flow.async_get_redirect_uri(self.hass)
        except NoURLAvailableError:
            redirect_url = config_entry_oauth2_flow.MY_AUTH_CALLBACK_PATH
        return self.async_show_form(
            step_id="bouncie",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLIENT_ID): str,
                    vol.Required(CONF_CLIENT_SECRET): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                }
            ),
            description_placeholders={
                "developer_portal_url": BOUNCIE_PORTAL_URL,
                "redirect_url": redirect_url,
            },
        )

    async def async_step_device_tracker(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """No login: pick from the trackers that have a location right now."""
        await self.async_set_unique_id(PROVIDER_HA_TRACKER)
        self._abort_if_unique_id_configured()
        devices = await HomeAssistantTrackers(self.hass).devices()
        self._devices = [d for d in devices if d.status == "online"]
        if not self._devices:
            return self.async_abort(reason="no_trackers")
        self._conn = {CONF_PROVIDER: PROVIDER_HA_TRACKER}
        self._title = "Home Assistant trackers"
        return await self.async_step_devices()

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

    async def async_on_create_entry(self, result: ConfigFlowResult) -> ConfigFlowResult:
        """Connected: go straight on to the first bus profile (closing it is fine, "Add bus
        profile" stays on the integration page)."""
        profile_flow = await self.hass.config_entries.subentries.async_init(
            (result["result"].entry_id, SUBENTRY_PROFILE),
            context=SubentryFlowContext(source=SOURCE_USER),
        )
        result["next_flow"] = (FlowType.CONFIG_SUBENTRIES_FLOW, profile_flow["flow_id"])
        return result

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
                await self._async_connect(self._session(), conn)
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

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_PROFILE: BusProfileSubentryFlow}


class BusMonitorOptionsFlow(OptionsFlow):
    """Settings for the provider connection (bus profiles are subentries)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    OPT_SCAN_INTERVAL: int(user_input[OPT_SCAN_INTERVAL]),
                    OPT_SHOW_PANEL: bool(user_input[OPT_SHOW_PANEL]),
                }
            )
        default, minimum = SCAN_INTERVALS[
            self.config_entry.data.get(CONF_PROVIDER, PROVIDER_TRACCAR)
        ]
        current = self.config_entry.options.get(OPT_SCAN_INTERVAL, default)
        show_panel = self.config_entry.options.get(OPT_SHOW_PANEL, True)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(OPT_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int), vol.Range(min=minimum, max=300)
                    ),
                    vol.Required(OPT_SHOW_PANEL, default=show_panel): bool,
                }
            ),
        )


class BusProfileSubentryFlow(ConfigSubentryFlow):
    """Add a bus profile, or reconfigure one: its settings, or its checkpoints."""

    @property
    def _entry(self) -> ConfigEntry:
        return self._get_entry()

    @property
    def _coord(self) -> Any:
        return getattr(self._entry, "runtime_data", None)

    def _device_options(self) -> list[selector.SelectOptionDict]:
        """The buses in use first, then every other vehicle the provider account can see,
        so a profile can move to a bus that wasn't picked at setup."""
        coord = self._coord
        devices = coord.devices if coord else {}
        in_use = list(coord.device_ids) if coord else list(map(str, self._entry.data[CONF_DEVICES]))
        others = sorted((i for i in devices if i not in in_use), key=lambda i: devices[i].name.lower())
        return [
            selector.SelectOptionDict(value=i, label=devices[i].name if i in devices else i)
            for i in in_use + others
        ]

    def _bus_position(self, device_id: str) -> dict[str, float] | None:
        coord = self._coord
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

    def _profile_schema(self, edit: bool = False) -> vol.Schema:
        """The bus profile form, shared by "add" and "reconfigure"."""
        season_end = default_season_end(dt_util.now().date()).isoformat()
        schema = vol.Schema(
            {
                vol.Required("name"): str,
                vol.Optional("announce_as"): str,
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
                vol.Required("season_end", default=season_end): selector.DateSelector(),
            }
        )
        if edit:
            schema = schema.extend({vol.Optional("relearn", default=False): bool})
        return schema

    @staticmethod
    def _season_end_error(user_input: dict[str, Any]) -> dict[str, str]:
        if date.fromisoformat(user_input["season_end"]) < dt_util.now().date():
            return {"season_end": "season_end_past"}
        return {}

    @staticmethod
    def _profile_fields(user_input: dict[str, Any], loc: dict[str, Any]) -> dict[str, Any]:
        """Stored profile settings from the form (checkpoints are kept separately)."""
        expected = user_input.get("expected_arrival")
        return {
            "device_id": str(user_input["device"]),
            "name": user_input["name"],
            "announce_as": (user_input.get("announce_as") or "").strip(),
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
            "season_end": user_input["season_end"],
        }

    # -- add ------------------------------------------------------------------------
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            loc = self._resolve_location(user_input, str(user_input["device"]))
            pid = slugify(user_input["name"])
            if not loc:
                errors["base"] = "location_required"
            elif season_error := self._season_end_error(user_input):
                errors.update(season_error)
            elif pid in taken_names(self.hass):
                errors["name"] = "name_exists"
            else:
                settings = {**self._profile_fields(user_input, loc), "checkpoints": []}
                return self.async_create_entry(
                    title=settings["name"],
                    data={**settings, CONF_PROFILE_ID: pid},
                    unique_id=pid,
                    description_placeholders={
                        "blueprint_url": BLUEPRINT_IMPORT_URL,
                        "guide_url": GUIDE_URL,
                    },
                )
        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=self.add_suggested_values_to_schema(
                self._profile_schema(), user_input or self._new_profile_suggestions()
            ),
        )

    def _new_profile_suggestions(self) -> dict[str, Any]:
        """Prefill the form: the first bus in use, the name "Morning" if it's free, and a stop
        at home. Without a value the map still draws a pin there, but ignores it until it's
        dragged, and then stores the map's own 1 km radius, so "arrived" comes far too early."""
        suggested: dict[str, Any] = {
            "device": self._device_options()[0]["value"],
            "location": {
                "latitude": self.hass.config.latitude,
                "longitude": self.hass.config.longitude,
                "radius": 75,
            },
        }
        if "morning" not in taken_names(self.hass):
            suggested["name"] = "Morning"
        return suggested

    # -- reconfigure ----------------------------------------------------------------
    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["profile", "add_checkpoint", "remove_checkpoints"],
            description_placeholders={"profile": self._get_reconfigure_subentry().title},
        )

    def _save(self, settings: dict[str, Any]) -> SubentryFlowResult:
        sub = self._get_reconfigure_subentry()
        return self.async_update_and_abort(
            self._entry,
            sub,
            title=settings.get("name", sub.title),
            data={**settings, CONF_PROFILE_ID: sub.data[CONF_PROFILE_ID]},
        )

    async def async_step_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change a profile's name, bus, stop or schedule. Its id stays the same, so recorded
        trips, checkpoints, entities and scripts that use `profile: <id>` keep working."""
        errors: dict[str, str] = {}
        sub = self._get_reconfigure_subentry()
        pid = sub.data[CONF_PROFILE_ID]
        current = profile_settings(sub)
        if user_input is not None:
            loc = self._resolve_location(user_input, str(user_input["device"]))
            if not loc:
                errors["base"] = "location_required"
            elif slugify(user_input["name"]) in taken_names(self.hass, except_id=pid):
                errors["name"] = "name_exists"
            elif season_error := self._season_end_error(user_input):
                errors.update(season_error)
            else:
                fields = self._profile_fields(user_input, loc)
                fields["stop"] = {**(current.get("stop") or {}), **fields["stop"]}
                if user_input.get("relearn") and self._coord is not None:
                    await self._coord.async_forget_trips(pid)
                return self._save({**current, **fields})
        stop = current.get("stop") or {}
        suggested: dict[str, Any] = {
            "name": current.get("name", pid),
            "announce_as": current.get("announce_as", ""),
            "device": str(current["device_id"]),
            "late_grace_min": stop.get("late_grace_min", 10),
            "active_start": current.get("active_start", "05:30"),
            "active_end": current.get("active_end", "09:30"),
            "weekdays": [str(d) for d in current.get("weekdays", [0, 1, 2, 3, 4])],
            "offline_after_min": current.get("offline_after_min", 0),
            "relearn": False,
        }
        today = dt_util.now().date()
        if current.get("season_end") and date.fromisoformat(current["season_end"]) >= today:
            suggested["season_end"] = current["season_end"]
        else:  # paused for the summer (or never set): suggest the coming school year's end
            suggested["season_end"] = default_season_end(today).isoformat()
        if stop:
            suggested["location"] = {
                "latitude": stop["lat"],
                "longitude": stop["lon"],
                "radius": stop.get("radius_m", 75),
            }
        if stop.get("expected_arrival"):
            suggested["expected_arrival"] = stop["expected_arrival"]
        return self.async_show_form(
            step_id="profile",
            errors=errors,
            data_schema=self.add_suggested_values_to_schema(
                self._profile_schema(edit=True), user_input or suggested
            ),
            description_placeholders={"profile_id": pid},
        )

    async def async_step_add_checkpoint(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        profile = profile_settings(self._get_reconfigure_subentry())
        if user_input is not None:
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
                return self._save(profile)
        return self.async_show_form(
            step_id="add_checkpoint",
            errors=errors,
            data_schema=vol.Schema(
                {
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

    async def async_step_remove_checkpoints(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        profile = profile_settings(self._get_reconfigure_subentry())
        if not profile["checkpoints"]:
            return self.async_abort(reason="no_checkpoints")
        if user_input is not None:
            drop = set(user_input.get("checkpoints", []))
            profile["checkpoints"] = [c for c in profile["checkpoints"] if c["label"] not in drop]
            return self._save(profile)
        labels = [c["label"] for c in profile["checkpoints"]]
        return self.async_show_form(
            step_id="remove_checkpoints",
            data_schema=vol.Schema(
                {
                    vol.Optional("checkpoints", default=[]): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=labels, multiple=True)
                    ),
                }
            ),
        )
