"""Per-trip alert state machine (no Home Assistant imports, fully unit-testable)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .geo import angle_diff_deg, bearing_deg, distance_to_segment_m, haversine_m
from .models import Alert, BusConfig, Checkpoint, Position

# If two fixes are further apart than this, don't trust a straight line between them.
MAX_SEGMENT_GAP = timedelta(seconds=120)
# Ignore tiny movements when deriving heading from consecutive fixes.
MIN_HEADING_MOVE_M = 15.0
MIN_COURSE_SPEED_MPS = 1.0

STATUS_IDLE = "idle"
STATUS_EN_ROUTE = "en_route"
STATUS_NEAR = "near"
STATUS_ARRIVED = "arrived"


class TripTracker:
    """Tracks one bus profile (one bus + one stop + one time window)."""

    def __init__(self, config: BusConfig) -> None:
        self.config = config
        # False until the first fix after Home Assistant starts or the entry reloads.
        # That fix only sets up state: we can't know what was already announced.
        self.seeded = False
        self.reset()

    # -- state ------------------------------------------------------------
    def reset(self, trip_date: date | None = None) -> None:
        self.trip_date: date | None = trip_date
        self.status = STATUS_IDLE
        self.prev: Position | None = None
        self.last_pos: Position | None = None
        self.last_fix: datetime | None = None
        self.fired: set[str] = set()
        self.crossings: dict[str, datetime] = {}
        self.arrival_time: datetime | None = None
        self.late_fired = False
        self.offline_fired = False
        # When this tracker started watching today's window. "Late" only fires for a
        # deadline that passed while we were watching: after a restart we can't tell
        # whether the bus already came, so we stay quiet rather than raise a false alarm.
        self.watching_since: datetime | None = None

    # -- persistence ------------------------------------------------------------
    def snapshot(self) -> dict | None:
        """Today's trip state, so a restart doesn't forget what was announced."""
        if self.trip_date is None:
            return None
        return {
            "date": self.trip_date.isoformat(),
            "status": self.status,
            "fired": sorted(self.fired),
            "crossings": {k: v.isoformat() for k, v in self.crossings.items()},
            "arrival": self.arrival_time.isoformat() if self.arrival_time else None,
            "late_fired": self.late_fired,
            "offline_fired": self.offline_fired,
        }

    def restore(self, data: dict | None, today: date) -> None:
        """Adopt a snapshot taken earlier today (ignored if it's from another day)."""
        if not data or data.get("date") != today.isoformat():
            return
        self.trip_date = today
        self.status = data.get("status", STATUS_IDLE)
        self.fired = set(data.get("fired", []))
        self.crossings = {k: datetime.fromisoformat(v) for k, v in data.get("crossings", {}).items()}
        arrival = data.get("arrival")
        self.arrival_time = datetime.fromisoformat(arrival) if arrival else None
        self.late_fired = bool(data.get("late_fired"))
        self.offline_fired = bool(data.get("offline_fired"))

    @property
    def arrived(self) -> bool:
        return self.arrival_time is not None

    def is_active(self, now: datetime) -> bool:
        cfg = self.config
        return now.weekday() in cfg.weekdays and cfg.active_start <= now.time() <= cfg.active_end

    # -- position updates ---------------------------------------------------
    def update(self, pos: Position, now: datetime) -> list[Alert]:
        """Feed a new fix; returns alerts that should fire."""
        self._roll_date(now)
        is_new_fix = self.last_fix is None or pos.fix_time > self.last_fix
        if not is_new_fix:
            return []
        self.last_fix = pos.fix_time
        self.last_pos = pos

        prev, self.prev = self.prev, pos
        if not self.is_active(now) or not pos.valid:
            return []
        self.watching_since = self.watching_since or now

        if not self.seeded:
            self._seed(pos)
            return []

        cfg = self.config
        stop = cfg.stop
        if self.arrived and stop is not None:
            if haversine_m(pos.lat, pos.lon, stop.lat, stop.lon) > 3 * stop.radius_m + 100:
                self.reset(self.trip_date)
                self.last_fix, self.last_pos, self.prev = pos.fix_time, pos, pos
            return []
        if self.status == STATUS_IDLE:
            self.status = STATUS_EN_ROUTE

        alerts: list[Alert] = []
        heading = self._heading(prev, pos)
        heading_ok = self._heading_ok(heading, pos)

        for announce in (True, False):
            group = [c for c in cfg.checkpoints if c.announce is announce]
            alerts.extend(self._process_checkpoints(group, prev, pos, heading_ok, announce))

        if stop is not None and self._crossed(stop.lat, stop.lon, stop.radius_m, prev, pos):
            self.arrival_time = pos.fix_time
            self.status = STATUS_ARRIVED
            self.fired.update(c.label for c in cfg.checkpoints)
            alerts.append(self._alert("arrived", "arrived", None, pos.fix_time, pos))
        return alerts

    def tick(self, now: datetime) -> list[Alert]:
        """Time-based checks (running late / offline); call on every refresh."""
        self._roll_date(now)
        if not self.is_active(now) or self.arrived:
            return []
        self.watching_since = self.watching_since or now
        cfg = self.config
        alerts: list[Alert] = []

        stop = cfg.stop
        if stop is not None and stop.expected_arrival is not None and not self.late_fired:
            expected = datetime.combine(now.date(), stop.expected_arrival, tzinfo=now.tzinfo)
            grace = timedelta(minutes=stop.late_grace_min)
            lead = max((c.minutes for c in cfg.checkpoints if c.announce), default=0)
            reached_first = any(c.label in self.crossings for c in cfg.checkpoints if c.announce)
            first_deadline = expected - timedelta(minutes=lead) + grace
            stop_deadline = expected + grace
            since = self.watching_since
            stage = None
            if not reached_first and lead and since <= first_deadline <= now:
                stage = "checkpoint"
            elif since <= stop_deadline <= now:
                stage = "stop"
            if stage:
                self.late_fired = True
                alerts.append(
                    self._alert("late", "late", None, now, self.last_pos, {"stage": stage})
                )

        if cfg.offline_after_min and not self.offline_fired:
            window_start = datetime.combine(now.date(), cfg.active_start, tzinfo=now.tzinfo)
            ref = max(self.last_fix, window_start) if self.last_fix else window_start
            if now - ref > timedelta(minutes=cfg.offline_after_min):
                self.offline_fired = True
                alerts.append(self._alert("offline", "offline", None, now, self.last_pos))
        return alerts

    # -- helpers ----------------------------------------------------------------
    def _seed(self, pos: Position) -> None:
        """First fix after a (re)start: adopt where the bus is without alerting.

        If the bus is already at the stop it counts as arrived; checkpoints it is
        sitting inside count as done, so a reload never repeats an announcement.
        """
        self.seeded = True
        if self.arrived:
            return  # restored from earlier today
        cfg = self.config
        stop = cfg.stop
        if stop is not None and haversine_m(pos.lat, pos.lon, stop.lat, stop.lon) <= stop.radius_m:
            self.arrival_time = pos.fix_time
            self.status = STATUS_ARRIVED
            self.fired.update(c.label for c in cfg.checkpoints)
            return
        if self.status == STATUS_IDLE:
            self.status = STATUS_EN_ROUTE
        for c in cfg.checkpoints:
            if haversine_m(pos.lat, pos.lon, c.lat, c.lon) <= c.radius_m:
                self.fired.add(c.label)

    def _roll_date(self, now: datetime) -> None:
        if self.trip_date != now.date():
            fix, pos, prev = self.last_fix, self.last_pos, self.prev
            self.reset(now.date())
            # keep the latest fix so a stale fix isn't re-processed as new
            self.last_fix, self.last_pos, self.prev = fix, pos, prev

    def _process_checkpoints(
        self,
        group: list[Checkpoint],
        prev: Position | None,
        pos: Position,
        heading_ok: bool,
        announce: bool,
    ) -> list[Alert]:
        if not heading_ok:
            return []
        crossed = [
            c
            for c in group
            if c.label not in self.fired
            and self._crossed(c.lat, c.lon, c.radius_m, prev, pos)
        ]
        if not crossed:
            return []
        chosen = min(crossed, key=lambda c: (c.minutes if c.minutes else 10_000))
        # Mark this checkpoint and every farther one as done, so a GPS gap
        # never produces a stale "10 minutes away" after "2 minutes away".
        for c in group:
            if c in crossed or (chosen.minutes and c.minutes > chosen.minutes):
                self.fired.add(c.label)
        for c in crossed:
            self.crossings.setdefault(c.label, pos.fix_time)
        if announce:
            self.status = STATUS_NEAR
        return [
            self._alert(
                "checkpoint",
                chosen.label,
                chosen.minutes or None,
                pos.fix_time,
                pos,
                announce=announce,
            )
        ]

    @staticmethod
    def _crossed(
        lat: float, lon: float, radius_m: float, prev: Position | None, pos: Position
    ) -> bool:
        if prev is None or pos.fix_time - prev.fix_time > MAX_SEGMENT_GAP:
            return haversine_m(pos.lat, pos.lon, lat, lon) <= radius_m
        return distance_to_segment_m(lat, lon, prev.lat, prev.lon, pos.lat, pos.lon) <= radius_m

    @staticmethod
    def _heading(prev: Position | None, pos: Position) -> float | None:
        if prev is not None and haversine_m(prev.lat, prev.lon, pos.lat, pos.lon) >= MIN_HEADING_MOVE_M:
            return bearing_deg(prev.lat, prev.lon, pos.lat, pos.lon)
        if pos.course is not None and pos.speed_mps >= MIN_COURSE_SPEED_MPS:
            return pos.course
        return None

    def _heading_ok(self, heading: float | None, pos: Position) -> bool:
        stop = self.config.stop
        if heading is None or stop is None:
            return True  # can't tell, don't suppress
        to_stop = bearing_deg(pos.lat, pos.lon, stop.lat, stop.lon)
        return angle_diff_deg(heading, to_stop) <= self.config.heading_tolerance_deg

    def _alert(
        self,
        kind: str,
        label: str,
        minutes: int | None,
        when: datetime,
        pos: Position | None,
        extra: dict | None = None,
        announce: bool = True,
    ) -> Alert:
        return Alert(
            kind=kind,
            profile_id=self.config.profile_id,
            device_id=self.config.device_id,
            bus_name=self.config.bus_name or self.config.name,
            profile_name=self.config.name,
            label=label,
            minutes=minutes,
            time=when,
            lat=pos.lat if pos else None,
            lon=pos.lon if pos else None,
            announce=announce,
            extra=extra or {},
        )
