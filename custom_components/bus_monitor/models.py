"""Plain data models shared by the alert engine, calibration and the HA layer."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any

from .geo import KNOTS_TO_MPS, MPH_TO_MPS

KIND_TIME = "time"
KIND_STREET = "street"


@dataclass(frozen=True)
class Position:
    """One GPS fix for one bus."""

    device_id: str
    lat: float
    lon: float
    fix_time: datetime  # timezone-aware
    speed_mps: float = 0.0
    course: float | None = None
    valid: bool = True

    @classmethod
    def from_traccar(cls, raw: dict[str, Any]) -> Position:
        """Build from a Traccar /api/positions item (speed is in knots)."""
        return cls(
            device_id=str(raw["deviceId"]),
            lat=float(raw["latitude"]),
            lon=float(raw["longitude"]),
            fix_time=parse_iso_time(raw["fixTime"]),
            speed_mps=float(raw.get("speed") or 0.0) * KNOTS_TO_MPS,
            course=float(raw["course"]) if raw.get("course") is not None else None,
            valid=bool(raw.get("valid", True)),
        )

    @classmethod
    def from_bouncie(cls, raw: dict[str, Any]) -> Position | None:
        """Build from a Bouncie /v1/vehicles item (speed is in mph); None if it has no location."""
        stats = raw.get("stats") or {}
        loc = stats.get("location")
        if not loc or loc.get("lat") is None or loc.get("lon") is None:
            return None
        return cls(
            device_id=str(raw["imei"]),
            lat=float(loc["lat"]),
            lon=float(loc["lon"]),
            fix_time=parse_iso_time(stats["lastUpdated"]),
            speed_mps=float(stats.get("speed") or 0.0) * MPH_TO_MPS,
            course=float(loc["heading"]) if loc.get("heading") is not None else None,
        )


def parse_iso_time(value: str) -> datetime:
    """Parse ISO timestamps such as 2026-10-15T12:47:01.000+0000 or ...Z."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


parse_traccar_time = parse_iso_time  # older name


@dataclass(frozen=True)
class Checkpoint:
    """A place on the route that triggers an announcement when the bus enters it.

    kind "time":   "about N minutes away"; `auto_place` lets recorded trips position it.
    kind "street": "Bus 12 is at <label>" (label is a street name, minutes unused).
    """

    label: str
    lat: float
    lon: float
    radius_m: float = 150.0
    minutes: int = 0  # nominal minutes-to-stop; 0 means unspecified
    announce: bool = True  # False = shadow mode (logged, never alerted)
    kind: str = KIND_TIME
    auto_place: bool = False

    @property
    def is_street(self) -> bool:
        return self.kind == KIND_STREET

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(
            label=str(data["label"]),
            lat=float(data["lat"]),
            lon=float(data["lon"]),
            radius_m=float(data.get("radius_m", 150.0)),
            minutes=int(data.get("minutes", 0)),
            announce=bool(data.get("announce", True)),
            kind=KIND_STREET if data.get("kind") == KIND_STREET else KIND_TIME,
            auto_place=bool(data.get("auto_place", False)) and data.get("kind") != KIND_STREET,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "lat": self.lat,
            "lon": self.lon,
            "radius_m": self.radius_m,
            "minutes": self.minutes,
            "announce": self.announce,
            "kind": self.kind,
            "auto_place": self.auto_place,
        }


@dataclass(frozen=True)
class StopConfig:
    """Where the kids get on or off, and when the bus is normally there."""

    lat: float
    lon: float
    radius_m: float = 75.0
    expected_arrival: time | None = None  # local time of day
    late_grace_min: int = 10  # minutes behind schedule at a checkpoint before "running late"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StopConfig:
        expected = data.get("expected_arrival")
        return cls(
            lat=float(data["lat"]),
            lon=float(data["lon"]),
            radius_m=float(data.get("radius_m", 75.0)),
            expected_arrival=time.fromisoformat(expected) if expected else None,
            late_grace_min=int(data.get("late_grace_min", 10)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "lat": self.lat,
            "lon": self.lon,
            "radius_m": self.radius_m,
            "expected_arrival": self.expected_arrival.isoformat(timespec="minutes")
            if self.expected_arrival
            else None,
            "late_grace_min": self.late_grace_min,
        }


@dataclass(frozen=True)
class BusConfig:
    """Everything the alert engine needs to know about one bus."""

    profile_id: str
    device_id: str
    name: str
    stop: StopConfig | None = None
    checkpoints: tuple[Checkpoint, ...] = ()
    heading_tolerance_deg: float = 100.0
    active_start: time = time(5, 30)
    active_end: time = time(9, 30)
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)  # Monday=0
    offline_after_min: int = 0  # 0 disables the "no GPS fix" alert
    bus_name: str = ""  # spoken name of the bus, e.g. "Bus 12" (set from the tracked vehicle)

    @classmethod
    def from_dict(cls, profile_id: str, data: dict[str, Any]) -> BusConfig:
        return cls(
            profile_id=profile_id,
            device_id=str(data["device_id"]),
            name=str(data.get("name", profile_id)),
            stop=StopConfig.from_dict(data["stop"]) if data.get("stop") else None,
            checkpoints=tuple(Checkpoint.from_dict(c) for c in data.get("checkpoints", [])),
            heading_tolerance_deg=float(data.get("heading_tolerance_deg", 100.0)),
            active_start=time.fromisoformat(data.get("active_start", "05:30")),
            active_end=time.fromisoformat(data.get("active_end", "09:30")),
            weekdays=tuple(data.get("weekdays", (0, 1, 2, 3, 4))),
            offline_after_min=int(data.get("offline_after_min", 0)),
            bus_name=str(data.get("announce_as") or "").strip(),
        )


@dataclass(frozen=True)
class Alert:
    """Something worth announcing."""

    kind: str  # "checkpoint" | "arrived" | "late" | "offline"
    profile_id: str
    device_id: str
    bus_name: str
    profile_name: str
    label: str
    minutes: int | None
    time: datetime
    lat: float | None = None
    lon: float | None = None
    announce: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def as_event_data(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "profile": self.profile_id,
            "device_id": self.device_id,
            "bus": self.bus_name,
            "profile_name": self.profile_name,
            "label": self.label,
            "minutes": self.minutes,
            "time": self.time.isoformat(),
            "latitude": self.lat,
            "longitude": self.lon,
            **self.extra,
        }


def bus_label(device_name: str) -> str:
    """How to say a vehicle name: a route number gets "Bus" ('12' -> 'Bus 12', '18 Orange' ->
    'Bus 18 Orange'); other names are said as is ('Bus 7', "Oleg's bus", 'Carpool van')."""
    name = device_name.strip()
    if name[:1].isdigit() and not re.search(r"\bbus\b", name, re.IGNORECASE):
        return f"Bus {name}"
    return name
