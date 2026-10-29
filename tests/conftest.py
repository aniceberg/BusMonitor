"""Shared fixtures and trail builders."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.bus_monitor.models import (
    BusConfig,
    Checkpoint,
    Position,
    StopConfig,
)

STOP_LAT, STOP_LON = 40.0, -75.0
MONDAY_7AM = datetime(2026, 10, 12, 7, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load custom_components in HA-level tests."""


def make_config(**overrides) -> BusConfig:
    base = {
        "profile_id": "am",
        "device_id": "1",
        "name": "Bus 12",
        "stop": StopConfig(STOP_LAT, STOP_LON, radius_m=75, late_grace_min=5),
        "checkpoints": (
            Checkpoint("10 min", 39.980, STOP_LON, radius_m=100, minutes=10),
            Checkpoint("5 min", 39.990, STOP_LON, radius_m=100, minutes=5),
            Checkpoint("2 min", 39.996, STOP_LON, radius_m=100, minutes=2),
        ),
    }
    base.update(overrides)
    return BusConfig(**base)


def pos(lat: float, lon: float = STOP_LON, at: datetime = MONDAY_7AM, **kw) -> Position:
    return Position(device_id="1", lat=lat, lon=lon, fix_time=at, **kw)


def northbound_trail(
    start_lat: float = 39.970, end_lat: float = STOP_LAT, step: float = 0.0005, start=MONDAY_7AM
):
    """Fixes every 15 s heading north along the stop's meridian."""
    out, lat, t = [], start_lat, start
    while lat <= end_lat + 1e-9:
        out.append(pos(lat, at=t, speed_mps=3.7, course=0.0))
        lat += step
        t += timedelta(seconds=15)
    return out
