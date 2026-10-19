"""'Where is the bus?' service logic."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from .coordinator import BusMonitorCoordinator
from .describe import compose, estimate_eta_min
from .geo import haversine_m
from .geocoder import GeocodeError
from .streets import describe_position

_LOGGER = logging.getLogger(__name__)


async def async_describe(
    hass: HomeAssistant, coordinator: BusMonitorCoordinator, profile: str
) -> dict[str, Any]:
    tracker = coordinator.trackers[profile]
    cfg = tracker.config
    pos = (coordinator.data or {}).get(cfg.device_id)
    if pos is None:
        return {"text": f"{cfg.bus_name or cfg.name} has no known location right now.", "known": False}

    now = dt_util.now()
    moving = pos.speed_mps >= 1.0
    heading = pos.course if moving else None

    info = None
    try:
        ways = await coordinator.geocoder.ways_near(pos.lat, pos.lon)
        info = describe_position(pos.lat, pos.lon, heading, ways)
    except GeocodeError as err:
        _LOGGER.warning("Street lookup failed: %s", err)

    stop = cfg.stop
    distance = haversine_m(pos.lat, pos.lon, stop.lat, stop.lon) if stop else None
    eta = estimate_eta_min(
        tracker.crossings, cfg.checkpoints, coordinator.recorder.trips_for(profile), now
    )
    text = compose(
        bus_name=cfg.bus_name or cfg.name,
        info=info,
        heading=heading,
        speed_mps=pos.speed_mps,
        age_s=(now - pos.fix_time).total_seconds(),
        distance_to_stop_m=distance,
        eta_min=eta,
        arrived=tracker.arrived,
        imperial=hass.config.units is US_CUSTOMARY_SYSTEM,
    )
    return {
        "known": True,
        "text": text,
        "street": info.street if info else None,
        "cross_street_behind": info.behind if info else None,
        "cross_street_ahead": info.ahead if info else None,
        "heading": heading,
        "latitude": pos.lat,
        "longitude": pos.lon,
        "distance_to_stop_m": round(distance) if distance is not None else None,
        "eta_minutes": eta,
        "status": tracker.status,
    }
