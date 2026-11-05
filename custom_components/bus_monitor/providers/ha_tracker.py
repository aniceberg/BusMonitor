"""Follow any device_tracker already in Home Assistant, from whichever integration made it."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from ..geo import bearing_deg, haversine_m
from ..models import Position
from .base import Device

TRACKER_DOMAIN = "device_tracker"
# A fix less accurate than this could land on the wrong side of a checkpoint.
MAX_ACCURACY_M = 250.0
# No newer fix for this long: stop saying the vehicle is moving.
MOTION_TIMEOUT = timedelta(minutes=2)
# Fixes closer together than this say little about speed.
MIN_MOTION_SECONDS = 1.0


def _coordinates(state: State) -> tuple[float, float] | None:
    """Where a tracker says it is; None for router and Bluetooth trackers, which don't say."""
    try:
        lat = float(state.attributes["latitude"])
        lon = float(state.attributes["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def _reporting(state: State) -> bool:
    return state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)


def _accurate(state: State) -> bool:
    try:
        return float(state.attributes["gps_accuracy"]) <= MAX_ACCURACY_M
    except (KeyError, TypeError, ValueError):
        return True  # not every tracker reports its accuracy


class HomeAssistantTrackers:
    """The "account" is this Home Assistant: its GPS trackers are the vehicles.

    A tracker's speed attribute has no agreed unit between integrations, so speed and course
    come from how far the tracker moved between fixes.
    """

    name = "Home Assistant"
    manufacturer = "Home Assistant"

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._last: dict[str, Position] = {}

    async def login(self) -> None:
        """Nothing to sign in to."""

    def _own_entities(self) -> set[str]:
        """Bus Monitor's own trackers, which only repeat what it already follows."""
        registry = er.async_get(self._hass)
        return {
            entry.entity_id
            for entry in registry.entities.values()
            if entry.platform == DOMAIN and entry.domain == TRACKER_DOMAIN
        }

    def _registered_name(self, entry: er.RegistryEntry) -> str:
        """A name for a tracker whose integration hasn't loaded yet."""
        own_name = entry.name or entry.original_name
        device = dr.async_get(self._hass).async_get(entry.device_id) if entry.device_id else None
        device_name = (device.name_by_user or device.name) if device else None
        if entry.has_entity_name and device_name:
            return f"{device_name} {own_name}" if own_name else device_name
        return own_name or device_name or entry.entity_id

    async def devices(self) -> list[Device]:
        """Trackers with a location, and registered ones that may have one once they load
        (status None), so a restart can't lose a bus's name."""
        found: dict[str, Device] = {}
        own = self._own_entities()
        for state in self._hass.states.async_all(TRACKER_DOMAIN):
            if state.entity_id not in own and _reporting(state) and _coordinates(state):
                found[state.entity_id] = Device(state.entity_id, state.name, state.entity_id, "online")
        for entry in er.async_get(self._hass).entities.values():
            if (
                entry.domain != TRACKER_DOMAIN
                or entry.entity_id in own
                or entry.entity_id in found
                or entry.disabled_by
            ):
                continue
            state = self._hass.states.get(entry.entity_id)
            if state is None or not _reporting(state):
                name = state.name if state else self._registered_name(entry)
                found[entry.entity_id] = Device(entry.entity_id, name, entry.entity_id)
        return list(found.values())

    async def positions(self) -> list[Position]:
        now = dt_util.utcnow()
        own = self._own_entities()
        result = []
        for state in self._hass.states.async_all(TRACKER_DOMAIN):
            if (
                state.entity_id in own
                or not _reporting(state)
                or (where := _coordinates(state)) is None
            ):
                continue
            position = self._position(state, *where, now)
            self._last[state.entity_id] = position
            result.append(position)
        return result

    def _position(self, state: State, lat: float, lon: float, now: datetime) -> Position:
        fix_time = state.last_updated
        last = self._last.get(state.entity_id)
        speed, course = 0.0, None
        if last is not None:
            speed, course = last.speed_mps, last.course
            seconds = (fix_time - last.fix_time).total_seconds()
            if (lat, lon) != (last.lat, last.lon) and seconds >= MIN_MOTION_SECONDS:
                speed = haversine_m(last.lat, last.lon, lat, lon) / seconds
                course = bearing_deg(last.lat, last.lon, lat, lon)
            elif (lat, lon) == (last.lat, last.lon) and seconds >= MIN_MOTION_SECONDS:
                speed = 0.0  # a new report from the same place
            if now - fix_time > MOTION_TIMEOUT:
                speed = 0.0
        return Position(
            device_id=state.entity_id,
            lat=lat,
            lon=lon,
            fix_time=fix_time,
            speed_mps=speed,
            course=course,
            valid=_accurate(state),
        )
