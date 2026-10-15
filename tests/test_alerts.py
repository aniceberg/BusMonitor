from datetime import time, timedelta

from custom_components.bus_monitor.alerts import TripTracker
from custom_components.bus_monitor.models import Checkpoint, StopConfig

from .conftest import MONDAY_7AM, STOP_LAT, STOP_LON, make_config, northbound_trail, pos


def run(tracker, trail):
    alerts = []
    for p in trail:
        alerts += tracker.update(p, p.fix_time)
        alerts += tracker.tick(p.fix_time)
    return alerts


def test_alerts_fire_once_in_order_then_arrive():
    tracker = TripTracker(make_config())
    alerts = run(tracker, northbound_trail())
    assert [a.label for a in alerts] == ["10 min", "5 min", "2 min", "arrived"]
    assert [a.minutes for a in alerts[:3]] == [10, 5, 2]
    assert tracker.status == "arrived"
    assert set(tracker.crossings) == {"10 min", "5 min", "2 min"}


def test_bus_heading_away_does_not_alert():
    tracker = TripTracker(make_config())
    trail = list(reversed(northbound_trail(start_lat=39.970, end_lat=39.9995)))
    # re-time so fix times still increase
    retimed = [pos(p.lat, at=MONDAY_7AM + timedelta(seconds=15 * i), speed_mps=3.7, course=180.0)
               for i, p in enumerate(trail)]
    # start just past the stop side of the checkpoints, heading south away from the stop
    alerts = run(tracker, retimed)
    assert [a.kind for a in alerts if a.kind == "checkpoint"] == []


def test_gps_gap_skips_stale_farther_checkpoints():
    tracker = TripTracker(make_config())
    t = MONDAY_7AM
    tracker.update(pos(39.970, at=t, speed_mps=10, course=0), t)
    t2 = t + timedelta(minutes=5)  # long gap: lands inside the 5 min radius
    alerts = tracker.update(pos(39.990, at=t2, speed_mps=10, course=0), t2)
    assert [a.label for a in alerts] == ["5 min"]
    # passing the 10 min point later must not re-announce
    t3 = t2 + timedelta(seconds=15)
    assert tracker.update(pos(39.9905, at=t3, speed_mps=10, course=0), t3) == []
    assert "10 min" in tracker.fired


def test_fast_bus_cannot_jump_over_small_radius():
    cps = (Checkpoint("tiny", 39.9800, STOP_LON, radius_m=20, minutes=5),)
    tracker = TripTracker(make_config(checkpoints=cps))
    t = MONDAY_7AM
    tracker.update(pos(39.9790, at=t, speed_mps=15, course=0), t)
    t2 = t + timedelta(seconds=15)
    alerts = tracker.update(pos(39.9810, at=t2, speed_mps=15, course=0), t2)  # 220 m hop
    assert [a.label for a in alerts] == ["tiny"]


def test_outside_active_window_is_silent():
    tracker = TripTracker(make_config(active_start=time(13, 0), active_end=time(16, 0)))
    assert run(tracker, northbound_trail()) == []


def test_weekend_is_silent():
    tracker = TripTracker(make_config(weekdays=(5, 6)))
    assert run(tracker, northbound_trail()) == []


def test_shadow_checkpoint_is_flagged_and_does_not_suppress_live():
    cps = (
        Checkpoint("live 5", 39.990, STOP_LON, radius_m=100, minutes=5),
        Checkpoint("shadow 8", 39.985, STOP_LON, radius_m=100, minutes=8, announce=False),
    )
    tracker = TripTracker(make_config(checkpoints=cps))
    alerts = run(tracker, northbound_trail())
    by_label = {a.label: a for a in alerts}
    assert by_label["shadow 8"].announce is False
    assert by_label["live 5"].announce is True
    assert "shadow 8" in tracker.crossings


def test_running_late_before_first_checkpoint():
    stop = StopConfig(STOP_LAT, STOP_LON, 75, expected_arrival=time(7, 30), late_grace_min=5)
    tracker = TripTracker(make_config(stop=stop))
    tracker.update(pos(39.950, speed_mps=0), MONDAY_7AM)
    # deadline = 07:30 - 10 + 5 = 07:25
    assert tracker.tick(MONDAY_7AM + timedelta(minutes=24)) == []
    late = tracker.tick(MONDAY_7AM + timedelta(minutes=26))
    assert [(a.kind, a.extra["stage"]) for a in late] == [("late", "checkpoint")]
    assert tracker.tick(MONDAY_7AM + timedelta(minutes=40)) == []  # only once


def test_not_late_when_on_schedule():
    stop = StopConfig(STOP_LAT, STOP_LON, 75, expected_arrival=time(7, 30), late_grace_min=5)
    tracker = TripTracker(make_config(stop=stop))
    t = MONDAY_7AM + timedelta(minutes=18)
    tracker.update(pos(39.9781, at=t, speed_mps=5, course=0), t)
    tracker.update(pos(39.9801, at=t + timedelta(seconds=15), speed_mps=5, course=0), t + timedelta(seconds=15))
    assert "10 min" in tracker.crossings
    assert tracker.tick(MONDAY_7AM + timedelta(minutes=26)) == []


def test_offline_alert_when_enabled():
    tracker = TripTracker(make_config(offline_after_min=10))
    tracker.update(pos(39.95, at=MONDAY_7AM, speed_mps=5, course=0), MONDAY_7AM)
    assert tracker.tick(MONDAY_7AM + timedelta(minutes=9)) == []
    alerts = tracker.tick(MONDAY_7AM + timedelta(minutes=11))
    assert [a.kind for a in alerts] == ["offline"]


def test_new_day_rearms_everything():
    tracker = TripTracker(make_config())
    run(tracker, northbound_trail())
    assert tracker.arrived
    next_day = MONDAY_7AM + timedelta(days=1)
    trail = [pos(p.lat, at=p.fix_time + timedelta(days=1), speed_mps=3.7, course=0.0)
             for p in northbound_trail()]
    alerts = run(tracker, trail)
    assert [a.label for a in alerts] == ["10 min", "5 min", "2 min", "arrived"]
    assert tracker.trip_date == next_day.date()
