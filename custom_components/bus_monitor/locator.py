"""'Where is the bus?' service logic."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from .const import DOMAIN
from .coordinator import BusMonitorCoordinator
from .describe import compose, estimate_eta_min, speakable
from .geo import haversine_m, offset_point
from .geocoder import GeocodeError, nominatim_road
from .streets import describe_position

_LOGGER = logging.getLogger(__name__)


async def async_describe(
    hass: HomeAssistant, coordinator: BusMonitorCoordinator, profile: str
) -> dict[str, Any]:
    tracker = coordinator.trackers[profile]
    cfg = tracker.config
    if not coordinator.needs_positions(dt_util.now()):
        # Not polling right now (outside the watch window, or the bus has arrived).
        try:
            await coordinator.async_fetch_now()
        except (UpdateFailed, ConfigEntryAuthFailed) as err:
            _LOGGER.warning("Couldn't refresh the bus position: %s", err)
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


STREET_LOOKUP_TIMEOUT_S = 12
CROSS_PROBE_M = 35


async def async_street_name(
    hass: HomeAssistant, lat: float, lon: float, bearing: float | None
) -> dict[str, Any]:
    """Name for a street checkpoint: the nearest cross street to the point.

    Overpass gives the full street network (best answer). It's often overloaded, so
    after a short wait fall back to Nominatim: the road at the point is the street
    the bus is on; the roads a few metres to either side of its direction of travel
    are the cross street at an intersection.
    """
    geocoder = hass.data.get(DOMAIN, {}).get("geocoder")
    if geocoder is not None:
        try:
            ways = await asyncio.wait_for(geocoder.ways_near(lat, lon), STREET_LOOKUP_TIMEOUT_S)
        except (GeocodeError, TimeoutError) as err:
            _LOGGER.debug("Overpass street lookup failed (%s), trying Nominatim", err)
        else:
            info = describe_position(lat, lon, bearing, ways)
            name = info.nearest_cross or info.street
            if name:
                return {"name": speakable(name), "street": info.street, "source": "overpass"}

    session = async_get_clientsession(hass)
    street = await nominatim_road(session, lat, lon)  # raises GeocodeError if unavailable
    cross = None
    if bearing is not None:
        for turn in (90, -90):
            plat, plon = offset_point(lat, lon, (bearing + turn) % 360, CROSS_PROBE_M)
            road = await nominatim_road(session, plat, plon)
            if road and road != street:
                cross = road
                break
    name = cross or street
    return {"name": speakable(name) if name else None, "street": street, "source": "nominatim"}
