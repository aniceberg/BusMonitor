"""Plain data models shared by the alert engine, calibration and the HA layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any

from .geo import KNOTS_TO_MPS


@dataclass(frozen=True)
class Position:
    """One GPS fix for one bus."""

    device_id: int
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
            device_id=int(raw["deviceId"]),
            lat=float(raw["latitude"]),
            lon=float(raw["longitude"]),
            fix_time=parse_traccar_time(raw["fixTime"]),
            speed_mps=float(raw.get("speed") or 0.0) * KNOTS_TO_MPS,
            course=float(raw["course"]) if raw.get("course") is not None else None,
            valid=bool(raw.get("valid", True)),
        )


def parse_traccar_time(value: str) -> datetime:
    """Parse Traccar timestamps such as 2026-10-15T12:47:01.000+0000."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


@dataclass(frozen=True)
class Checkpoint:
    """A place that, when the bus passes it, means 'about N minutes away'."""

    label: str
    lat: float
    lon: float
    radius_m: float = 150.0
    minutes: int = 0  # nominal minutes-to-stop; 0 means unspecified
    announce: bool = True  # False = shadow mode (logged, never alerted)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(
            label=str(data["label"]),
            lat=float(data["lat"]),
            lon=float(data["lon"]),
            radius_m=float(data.get("radius_m", 150.0)),
            minutes=int(data.get("minutes", 0)),
            announce=bool(data.get("announce", True)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "lat": self.lat,
            "lon": self.lon,
            "radius_m": self.radius_m,
            "minutes": self.minutes,
            "announce": self.announce,
        }


@dataclass(frozen=True)
class StopConfig:
    """Where the kids get on or off, and when the bus is normally there."""

    lat: float
    lon: float
    radius_m: float = 75.0
    expected_arrival: time | None = None  # local time of day
    late_grace_min: int = 5

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StopConfig:
        expected = data.get("expected_arrival")
        return cls(
            lat=float(data["lat"]),
            lon=float(data["lon"]),
            radius_m=float(data.get("radius_m", 75.0)),
            expected_arrival=time.fromisoformat(expected) if expected else None,
            late_grace_min=int(data.get("late_grace_min", 5)),
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
    device_id: int
    name: str
    stop: StopConfig | None = None
    checkpoints: tuple[Checkpoint, ...] = ()
    heading_tolerance_deg: float = 100.0
    active_start: time = time(5, 30)
    active_end: time = time(9, 30)
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)  # Monday=0
    offline_after_min: int = 0  # 0 disables the "no GPS fix" alert
    bus_name: str = ""  # spoken name of the bus, e.g. "Bus 72" (set from the Traccar device)

    @classmethod
    def from_dict(cls, profile_id: str, data: dict[str, Any]) -> BusConfig:
        return cls(
            profile_id=profile_id,
            device_id=int(data["device_id"]),
            name=str(data.get("name", profile_id)),
            stop=StopConfig.from_dict(data["stop"]) if data.get("stop") else None,
            checkpoints=tuple(Checkpoint.from_dict(c) for c in data.get("checkpoints", [])),
            heading_tolerance_deg=float(data.get("heading_tolerance_deg", 100.0)),
            active_start=time.fromisoformat(data.get("active_start", "05:30")),
            active_end=time.fromisoformat(data.get("active_end", "09:30")),
            weekdays=tuple(data.get("weekdays", (0, 1, 2, 3, 4))),
            offline_after_min=int(data.get("offline_after_min", 0)),
        )


@dataclass(frozen=True)
class Alert:
    """Something worth announcing."""

    kind: str  # "checkpoint" | "arrived" | "late" | "offline"
    profile_id: str
    device_id: int
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
    """How to say a Traccar device name: '72' -> 'Bus 72', 'Bus 12' stays as is."""
    name = device_name.strip()
    return name if name.lower().startswith("bus") else f"Bus {name}"
