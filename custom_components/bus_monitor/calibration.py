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
# typical_position ignores trips whose remaining distance differs from the median trip's
# by more than this share of it (or this many metres, whichever is larger).
OUTLIER_FRACTION = 0.25
OUTLIER_MIN_M = 100.0
# An in-progress trail older than this at startup belongs to an earlier trip.
CURRENT_TRAIL_MAX_AGE = timedelta(hours=3)


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
        if trail and pos.fix_time - trail[-1][0] > CURRENT_TRAIL_MAX_AGE:
            # Left over from an earlier trip that never reached the stop: start afresh
            # so it can't be glued onto today's trip (and pollute the heatmap).
            trail.clear()
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

    def current_trail(self, profile_id: str) -> list[tuple[datetime, float, float, float]]:
        return list(self._current.get(profile_id, []))

    def as_dict(self) -> dict[str, Any]:
        return {
            "trips": [t.as_dict() for t in self.trips],
            "current": {
                pid: [[t.isoformat(), la, lo, s] for t, la, lo, s in trail]
                for pid, trail in self._current.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, now: datetime | None = None) -> TrailRecorder:
        """Load saved trips; in-progress trails are kept only if recent (same trip)."""
        rec = cls()
        if data:
            rec.trips = [TripRecord.from_dict(t) for t in data.get("trips", [])]
            for pid, raw in (data.get("current") or {}).items():
                trail = [(datetime.fromisoformat(t), la, lo, s) for t, la, lo, s in raw]
                if trail and now is not None and now - trail[-1][0] < CURRENT_TRAIL_MAX_AGE:
                    rec._current[pid] = trail
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


def _cumulative(trail: list[tuple[datetime, float, float, float]]) -> list[float]:
    out = [0.0]
    for (_, la1, lo1, _), (_, la2, lo2, _) in zip(trail, trail[1:], strict=False):
        out.append(out[-1] + haversine_m(la1, lo1, la2, lo2))
    return out


def _remaining_at(trip: TripRecord, cum: list[float], when: datetime) -> float | None:
    """Along-route metres still to go to the stop at `when` (trail ends at arrival)."""
    trail = trip.trail
    if not trail or when < trail[0][0] or when > trail[-1][0]:
        return None
    for k in range(1, len(trail)):
        t1, t2 = trail[k - 1][0], trail[k][0]
        if t1 <= when <= t2:
            span = (t2 - t1).total_seconds()
            f = 0.0 if span == 0 else (when - t1).total_seconds() / span
            return cum[-1] - (cum[k - 1] + (cum[k] - cum[k - 1]) * f)
    return None


def _point_at_remaining(trip: TripRecord, cum: list[float], remaining: float) -> tuple[float, float] | None:
    """The point on this trip's trail `remaining` metres (along the route) before the stop."""
    target = cum[-1] - remaining
    if target < 0:
        return None
    trail = trip.trail
    for k in range(1, len(trail)):
        if cum[k - 1] <= target <= cum[k]:
            seg = cum[k] - cum[k - 1]
            f = 0.0 if seg == 0 else (target - cum[k - 1]) / seg
            return interpolate(trail[k - 1][1], trail[k - 1][2], trail[k][1], trail[k][2], f)
    return None


def typical_position(
    trips: list[TripRecord], minutes: float, last_n: int = 20, min_trips: int = 1
) -> dict[str, Any] | None:
    """Where the bus usually is `minutes` before reaching the stop, robust to odd days.

    1. For each trip, how far (along its own route) it still had to go at that time.
    2. Average of the majority: trips whose distance is far from the median trip's
       (a late-running or unusually early day) are left out, then the rest are
       averaged. Up to just under half the trips can be odd without moving the spot.
    3. On each remaining trip, the point that far from the stop; the coordinate-wise
       median of those points sits on the usual road even if one trip detoured.
    """
    recent = sorted(trips, key=lambda t: t.date)[-last_n:]
    samples = []
    for t in recent:
        cum = _cumulative(t.trail)
        rem = _remaining_at(t, cum, t.arrival - timedelta(minutes=minutes))
        if rem is not None:
            samples.append((rem, t, cum))
    if len(samples) < max(1, min_trips):
        return None
    med = statistics.median(s[0] for s in samples)
    band = max(OUTLIER_FRACTION * med, OUTLIER_MIN_M)
    kept = [s for s in samples if abs(s[0] - med) <= band]
    if len(kept) * 2 < len(samples):  # no clear majority: just use the median trip
        kept = sorted(samples, key=lambda s: abs(s[0] - med))[: max(1, len(samples) // 2)]
    distance = statistics.fmean(s[0] for s in kept)
    points = [p for _, t, cum in kept if (p := _point_at_remaining(t, cum, distance)) is not None]
    if not points:
        return None
    lat = statistics.median(p[0] for p in points)
    lon = statistics.median(p[1] for p in points)
    spread = statistics.median(haversine_m(lat, lon, p[0], p[1]) for p in points)
    return {
        "minutes": minutes,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "trips": len(kept),
        "spread_m": round(spread),
        "distance_m": round(distance),
    }


def suggest_checkpoints(
    trips: list[TripRecord], target_minutes: list[int], last_n: int = 20
) -> list[dict[str, Any]]:
    """For each target T, the typical place the bus was T minutes before arriving
    (see `typical_position`). `spread_m` is how far individual trips were from it;
    a large spread means the route varies there and the suggestion is weak."""
    return [
        p
        for minutes in target_minutes
        if (p := typical_position(trips, minutes, last_n=last_n)) is not None
    ]
