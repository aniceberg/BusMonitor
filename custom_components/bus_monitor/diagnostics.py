"""Diagnostics download, safe to attach to a public GitHub issue.

Everything here is copied field by field instead of redacted from the stored data, so a setting
added later stays out until someone decides it's safe. Left out on purpose: server addresses,
logins, tokens, account and vehicle names and ids, profile names, spoken names, street names,
and every coordinate (stops, checkpoints, positions, recorded trips).
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CONF_BASE_URL, CONF_DEVICES, CONF_PROVIDER
from .profiles import entry_profiles


def _vehicles(entry: ConfigEntry, coord: Any) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """The vehicles under stable neutral references, and {real id: reference}."""
    selected = [str(i) for i in entry.data.get(CONF_DEVICES, [])]
    ids = list(selected)
    if coord is not None:
        ids += [i for i in coord.devices if i not in ids]
    for profile in entry_profiles(entry).values():
        if str(profile["device_id"]) not in ids:
            ids.append(str(profile["device_id"]))
    refs = {device_id: f"vehicle_{n}" for n, device_id in enumerate(ids, start=1)}
    now = dt_util.utcnow()
    vehicles = []
    for device_id in ids:
        device = coord.devices.get(device_id) if coord is not None else None
        pos = (coord.data or {}).get(device_id) if coord is not None else None
        vehicles.append(
            {
                "ref": refs[device_id],
                "selected_at_setup": device_id in selected,
                "seen_on_account": device is not None if coord is not None else None,
                "status": device.status if device else None,
                "fix": {
                    "age_seconds": round((now - pos.fix_time).total_seconds()),
                    "valid": pos.valid,
                    "speed_mps": pos.speed_mps,
                }
                if pos
                else None,
            }
        )
    return vehicles, refs


def _profile(n: int, pid: str, raw: dict[str, Any], refs: dict[str, str], coord: Any) -> dict:
    stop = raw.get("stop") or {}
    checkpoints = raw.get("checkpoints") or []
    tracker = coord.trackers.get(pid) if coord is not None else None
    alert = coord.last_alert.get(pid) if coord is not None else None
    return {
        "ref": f"profile_{n}",
        "vehicle": refs.get(str(raw.get("device_id"))),
        "announce_as_set": bool(raw.get("announce_as")),
        "active_start": raw.get("active_start"),
        "active_end": raw.get("active_end"),
        "weekdays": raw.get("weekdays"),
        "season_end": raw.get("season_end"),
        "offline_after_min": raw.get("offline_after_min"),
        "stop": {
            "set": bool(stop),
            "radius_m": stop.get("radius_m"),
            "expected_arrival": stop.get("expected_arrival"),
            "late_grace_min": stop.get("late_grace_min"),
        },
        "checkpoints": {
            "total": len(checkpoints),
            "street": sum(c.get("kind") == "street" for c in checkpoints),
            "auto_placed": sum(bool(c.get("auto_place")) for c in checkpoints),
            "shadow": sum(not c.get("announce", True) for c in checkpoints),
        },
        "status": tracker.display_status(dt_util.now()) if tracker else None,
        "last_alert_kind": alert.kind if alert else None,
        "trips_recorded": len(coord.recorder.trips_for(pid)) if coord is not None else None,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """State of one provider connection, with nothing that identifies a person or a place."""
    coord = getattr(entry, "runtime_data", None)
    vehicles, refs = _vehicles(entry, coord)
    base_url = str(entry.data.get(CONF_BASE_URL, ""))
    error = coord.last_exception if coord is not None else None
    return {
        "entry": {
            "provider": entry.data.get(CONF_PROVIDER),
            "state": entry.state.value,
            "version": f"{entry.version}.{entry.minor_version}",
            # Whether the login travels encrypted, without saying where it goes.
            "server_scheme": base_url.split("://", 1)[0] if "://" in base_url else None,
            "scan_interval": entry.options.get("scan_interval"),
            "show_panel": entry.options.get("show_panel"),
        },
        "polling": {
            "last_update_success": coord.last_update_success,
            # The type only: messages can contain the server address.
            "last_error": type(error).__name__ if error else None,
            "update_interval_seconds": coord.update_interval.total_seconds()
            if coord.update_interval
            else None,
        }
        if coord is not None
        else None,
        "vehicles": vehicles,
        "profiles": [
            _profile(n, pid, raw, refs, coord)
            for n, (pid, raw) in enumerate(entry_profiles(entry).items(), start=1)
        ],
    }
