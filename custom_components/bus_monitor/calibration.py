"""Trail recording and baseline statistics (no Home Assistant imports)."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .geo import haversine_m, interpolate
from .models import Position

MIN_SAMPLE_INTERVAL = timedelta(seconds=10)
RETENTION_DAYS = 60


@dataclass
class TripRecord:
    """One completed trip: the trail, checkpoint crossings and stop arrival."""

    profile_id: str
    date: str  # ISO local date
    arrival: datetime
    crossings: dict[str, datetime]
    trail: list[tuple[datetime, float, float, float]]  # time, lat, lon, speed_mps

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "date": self.date,
            "arrival": self.arrival.isoformat(),
            "crossings": {k: v.isoformat() for k, v in self.crossings.items()},
            "trail": [[t.isoformat(), round(la, 6), round(lo, 6), round(s, 1)] for t, la, lo, s in self.trail],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TripRecord:
        return cls(
            profile_id=data["profile_id"],
            date=data["date"],
            arrival=datetime.fromisoformat(data["arrival"]),
            crossings={k: datetime.fromisoformat(v) for k, v in data["crossings"].items()},
            trail=[(datetime.fromisoformat(t), la, lo, s) for t, la, lo, s in data["trail"]],
        )


@dataclass
class TrailRecorder:
    """Accumulates the in-progress trail for each profile and stores finished trips."""

    trips: list[TripRecord] = field(default_factory=list)
    _current: dict[str, list[tuple[datetime, float, float, float]]] = field(default_factory=dict)

    def add_point(self, profile_id: str, pos: Position) -> None:
        trail = self._current.setdefault(profile_id, [])
        if trail and pos.fix_time - trail[-1][0] < MIN_SAMPLE_INTERVAL:
            return
        trail.append((pos.fix_time, pos.lat, pos.lon, pos.speed_mps))

    def discard(self, profile_id: str) -> None:
        self._current.pop(profile_id, None)

    def finish(
        self,
        profile_id: str,
        trip_date: str,
        arrival: datetime,
        crossings: dict[str, datetime],
    ) -> TripRecord | None:
        trail = self._current.pop(profile_id, [])
        if len(trail) < 2:
            return None
        record = TripRecord(profile_id, trip_date, arrival, dict(crossings), trail)
        # one trip per profile per day: later one replaces earlier
        self.trips = [t for t in self.trips if not (t.profile_id == profile_id and t.date == trip_date)]
        self.trips.append(record)
        cutoff = (arrival - timedelta(days=RETENTION_DAYS)).date().isoformat()
        self.trips = [t for t in self.trips if t.date >= cutoff]
        return record

    def trips_for(self, profile_id: str) -> list[TripRecord]:
        return [t for t in self.trips if t.profile_id == profile_id]

    def as_dict(self) -> dict[str, Any]:
        return {"trips": [t.as_dict() for t in self.trips]}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> TrailRecorder:
        rec = cls()
        if data:
            rec.trips = [TripRecord.from_dict(t) for t in data.get("trips", [])]
        return rec


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * pct / 100
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def checkpoint_stats(trips: list[TripRecord], label: str, last_n: int = 20) -> dict[str, Any] | None:
    """Actual minutes between crossing `label` and arriving at the stop."""
    recent = sorted(trips, key=lambda t: t.date)[-last_n:]
    minutes = [
        (t.arrival - t.crossings[label]).total_seconds() / 60
        for t in recent
        if label in t.crossings and t.arrival > t.crossings[label]
    ]
    if not minutes:
        return None
    return {
        "count": len(minutes),
        "median": round(statistics.median(minutes), 1),
        "p10": round(_percentile(minutes, 10), 1),
        "p90": round(_percentile(minutes, 90), 1),
    }


def position_at(
    trail: list[tuple[datetime, float, float, float]], when: datetime
) -> tuple[float, float] | None:
    """Interpolated trail position at `when`, or None if outside the trail."""
    if not trail or when < trail[0][0] or when > trail[-1][0]:
        return None
    for (t1, la1, lo1, _), (t2, la2, lo2, _) in zip(trail, trail[1:], strict=False):
        if t1 <= when <= t2:
            span = (t2 - t1).total_seconds()
            frac = 0.0 if span == 0 else (when - t1).total_seconds() / span
            return interpolate(la1, lo1, la2, lo2, frac)
    return None


def suggest_checkpoints(
    trips: list[TripRecord], target_minutes: list[int], last_n: int = 20
) -> list[dict[str, Any]]:
    """For each target T, the typical place the bus was T minutes before arriving.

    Uses the coordinate-wise median across trips (fine for a fixed route) and
    reports `spread_m`, the median distance of individual trips from that
    point; a large spread means the route varies and the suggestion is weak.
    """
    recent = sorted(trips, key=lambda t: t.date)[-last_n:]
    out: list[dict[str, Any]] = []
    for minutes in target_minutes:
        points = [
            p
            for t in recent
            if (p := position_at(t.trail, t.arrival - timedelta(minutes=minutes))) is not None
        ]
        if not points:
            continue
        lat = statistics.median(p[0] for p in points)
        lon = statistics.median(p[1] for p in points)
        spread = statistics.median(haversine_m(lat, lon, p[0], p[1]) for p in points)
        out.append(
            {
                "minutes": minutes,
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "trips": len(points),
                "spread_m": round(spread),
            }
        )
    return out
