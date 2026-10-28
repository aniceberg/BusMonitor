"""Websocket API used by the Bus Monitor panel."""

from __future__ import annotations

import copy
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .calibration import suggest_checkpoints
from .const import DOMAIN, OPT_PROFILES
from .coordinator import MIN_AUTO_TRIPS
from .geocoder import GeocodeError
from .heatmap import route_heatmap
from .locator import async_street_name
from .models import KIND_STREET, KIND_TIME

MAX_MINUTE_MARKS = 30

CHECKPOINT_SCHEMA = vol.Schema(
    {
        vol.Required("label"): vol.All(str, vol.Length(min=1, max=60)),
        vol.Required("minutes"): vol.All(vol.Coerce(int), vol.Range(min=0, max=90)),
        vol.Required("lat"): vol.All(vol.Coerce(float), vol.Range(min=-90, max=90)),
        vol.Required("lon"): vol.All(vol.Coerce(float), vol.Range(min=-180, max=180)),
        vol.Required("radius_m"): vol.All(vol.Coerce(float), vol.Range(min=10, max=1000)),
        vol.Optional("announce", default=True): bool,
        vol.Optional("kind", default=KIND_TIME): vol.In([KIND_TIME, KIND_STREET]),
        vol.Optional("auto_place", default=False): bool,
    }
)


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    data = hass.data.setdefault(DOMAIN, {})
    if data.get("ws_registered"):
        return
    websocket_api.async_register_command(hass, ws_overview)
    websocket_api.async_register_command(hass, ws_route)
    websocket_api.async_register_command(hass, ws_set_checkpoints)
    websocket_api.async_register_command(hass, ws_street_name)
    data["ws_registered"] = True


def _find(hass: HomeAssistant, profile: str):
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        if profile in entry.runtime_data.trackers:
            return entry, entry.runtime_data
    return None, None


@websocket_api.websocket_command({vol.Required("type"): "bus_monitor/overview"})
@callback
def ws_overview(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Profiles with their stop, checkpoints and the bus's live position."""
    registry = er.async_get(hass)
    profiles: list[dict[str, Any]] = []
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coord = entry.runtime_data
        for pid, tracker in coord.trackers.items():
            cfg = tracker.config
            pos = (coord.data or {}).get(cfg.device_id)
            profiles.append(
                {
                    "id": pid,
                    "name": cfg.name,
                    "bus": cfg.bus_name or cfg.name,
                    "device_id": cfg.device_id,
                    "tracker_entity": registry.async_get_entity_id(
                        "device_tracker", DOMAIN, f"{entry.entry_id}_{cfg.device_id}_tracker"
                    ),
                    "stop": cfg.stop.as_dict() if cfg.stop else None,
                    # effective positions (auto-placed ones where they currently are)
                    "checkpoints": [
                        {
                            **c.as_dict(),
                            "auto_trips": (coord.auto_positions.get(pid, {}).get(c.label) or [None] * 3)[2],
                        }
                        for c in cfg.checkpoints
                    ],
                    "min_auto_trips": MIN_AUTO_TRIPS,
                    "window": [
                        cfg.active_start.isoformat(timespec="minutes"),
                        cfg.active_end.isoformat(timespec="minutes"),
                    ],
                    "status": tracker.status,
                    "trips": len(coord.recorder.trips_for(pid)),
                    "position": {
                        "lat": pos.lat,
                        "lon": pos.lon,
                        "course": pos.course,
                        "speed_mps": pos.speed_mps,
                        "fix_time": pos.fix_time.isoformat(),
                    }
                    if pos
                    else None,
                }
            )
    connection.send_result(
        msg["id"], {"profiles": profiles, "can_edit": bool(connection.user and connection.user.is_admin)}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "bus_monitor/route",
        vol.Required("profile"): str,
        vol.Optional("days", default=60): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
    }
)
@callback
def ws_route(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Recorded trips for the map: latest trip, today's trail so far, and the heatmap."""
    _, coord = _find(hass, msg["profile"])
    if coord is None:
        connection.send_error(msg["id"], "not_found", "Unknown bus profile")
        return
    trips = sorted(coord.recorder.trips_for(msg["profile"]), key=lambda t: t.date)[-msg["days"] :]
    latest = trips[-1] if trips else None
    connection.send_result(
        msg["id"],
        {
            "trips": len(trips),
            "dates": [t.date for t in trips],
            "latest": {
                "date": latest.date,
                "path": [[la, lo] for _, la, lo, _ in latest.trail],
            }
            if latest
            else None,
            "today": [[la, lo] for _, la, lo, _ in coord.recorder.current_trail(msg["profile"])],
            "heatmap": route_heatmap(trips),
            # Where the bus typically is N minutes before reaching the stop.
            "minute_marks": suggest_checkpoints(trips, list(range(1, MAX_MINUTE_MARKS + 1))),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "bus_monitor/set_checkpoints",
        vol.Required("profile"): str,
        vol.Required("checkpoints"): [CHECKPOINT_SCHEMA],
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_checkpoints(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Replace a profile's checkpoints (the entry reloads to apply them)."""
    entry, _ = _find(hass, msg["profile"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown bus profile")
        return
    labels = [c["label"].strip() for c in msg["checkpoints"]]
    if len(set(labels)) != len(labels):
        connection.send_error(msg["id"], "invalid_format", "Checkpoint names must be unique")
        return
    profiles = copy.deepcopy(dict(entry.options.get(OPT_PROFILES) or {}))
    profiles[msg["profile"]]["checkpoints"] = [
        {**c, "label": c["label"].strip()} for c in msg["checkpoints"]
    ]
    hass.config_entries.async_update_entry(entry, options={**entry.options, OPT_PROFILES: profiles})
    connection.send_result(msg["id"], {"saved": len(labels)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "bus_monitor/street_name",
        vol.Required("lat"): vol.Coerce(float),
        vol.Required("lon"): vol.Coerce(float),
        vol.Optional("bearing"): vol.Any(None, vol.Coerce(float)),
    }
)
@websocket_api.async_response
async def ws_street_name(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Name for a street checkpoint: the nearest cross street to the point."""
    try:
        result = await async_street_name(hass, msg["lat"], msg["lon"], msg.get("bearing"))
    except GeocodeError as err:
        connection.send_error(msg["id"], "lookup_failed", f"Street lookup failed: {err}")
        return
    connection.send_result(msg["id"], result)
