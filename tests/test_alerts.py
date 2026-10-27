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


def test_first_fix_at_stop_is_silent_arrival():
    """A reload while the bus waits at the stop must not repeat 'arrived'."""
    tracker = TripTracker(make_config())
    t = MONDAY_7AM
    assert tracker.update(pos(STOP_LAT, at=t, speed_mps=0), t) == []
    assert tracker.status == "arrived"
    t2 = t + timedelta(seconds=10)
    assert tracker.update(pos(STOP_LAT + 0.0001, at=t2, speed_mps=0), t2) == []


def test_first_fix_inside_checkpoint_does_not_reannounce_it():
    tracker = TripTracker(make_config())
    t = MONDAY_7AM
    assert tracker.update(pos(39.990, at=t, speed_mps=5, course=0), t) == []  # inside "5 min"
    trail = [pos(39.9905 + i * 0.0005, at=t + timedelta(seconds=15 * (i + 1)), speed_mps=5, course=0)
             for i in range(20)]
    alerts = [a.label for p in trail for a in tracker.update(p, p.fix_time)]
    assert alerts == ["2 min", "arrived"]


def test_alert_uses_bus_name_and_keeps_profile_name():
    tracker = TripTracker(make_config(name="Morning", bus_name="Bus 12"))
    alerts = run(tracker, northbound_trail())
    data = alerts[-1].as_event_data()
    assert (data["bus"], data["profile_name"], data["kind"]) == ("Bus 12", "Morning", "arrived")


def test_bus_label():
    from custom_components.bus_monitor.models import bus_label

    assert bus_label("12") == "Bus 12"
    assert bus_label("18 Orange") == "Bus 18 Orange"
    assert bus_label("Bus 12") == "Bus 12"


def test_no_late_alarm_when_watching_starts_after_the_deadline():
    """HA restarted after the bus already came and went: stay quiet, don't say 'late'."""
    stop = StopConfig(STOP_LAT, STOP_LON, 75, expected_arrival=time(7, 30), late_grace_min=5)
    tracker = TripTracker(make_config(stop=stop))
    restart = MONDAY_7AM + timedelta(minutes=53)  # 07:53, deadlines were 07:25 and 07:35
    tracker.update(pos(39.95, at=restart, speed_mps=5, course=180), restart)
    assert tracker.tick(restart) == []
    assert tracker.tick(restart + timedelta(minutes=20)) == []


def test_snapshot_restore_keeps_arrival_and_skips_other_days():
    tracker = TripTracker(make_config())
    run(tracker, northbound_trail())
    snap = tracker.snapshot()
    assert snap["arrival"] and snap["status"] == "arrived"

    fresh = TripTracker(make_config())
    fresh.restore(snap, MONDAY_7AM.date())
    assert fresh.arrived and set(fresh.crossings) == {"10 min", "5 min", "2 min"}
    # after a restart the bus is away from the stop: still arrived, nothing fires
    t = MONDAY_7AM + timedelta(hours=1)
    assert fresh.update(pos(39.99, at=t, speed_mps=5, course=180), t) == []
    assert fresh.tick(t) == []

    other = TripTracker(make_config())
    other.restore(snap, (MONDAY_7AM + timedelta(days=1)).date())
    assert not other.arrived


def test_bus_leaving_after_arrival_never_announces_late():
    """Regression: arrived, drove off, then 'running late' was announced anyway."""
    stop = StopConfig(STOP_LAT, STOP_LON, 87, expected_arrival=time(7, 30), late_grace_min=15)
    tracker = TripTracker(make_config(stop=stop))
    alerts = run(tracker, northbound_trail())  # arrives ~07:15
    assert alerts[-1].kind == "arrived"
    # bus drives on, well past the stop, then back south through every checkpoint
    t = alerts[-1].time
    later = []
    for i, lat in enumerate([STOP_LAT + 0.004, STOP_LAT + 0.006, 39.996, 39.990, 39.980, 39.975]):
        when = t + timedelta(minutes=2 * (i + 1))
        later += tracker.update(pos(lat, at=when, speed_mps=8, course=180), when)
        later += tracker.tick(when)
    later += tracker.tick(MONDAY_7AM + timedelta(minutes=46))  # past 07:45 stop deadline
    assert later == []
    assert tracker.status == "arrived" and not tracker.late_fired


# --- running late: first missed checkpoint -------------------------------------------

def _late_tracker(tolerance=10, **kw):
    stop = StopConfig(STOP_LAT, STOP_LON, 75, expected_arrival=time(7, 30), late_grace_min=tolerance)
    tracker = TripTracker(make_config(stop=stop, **kw))
    tracker.update(pos(39.95, at=MONDAY_7AM, speed_mps=5, course=0), MONDAY_7AM)  # seed at 07:00
    return tracker


def _at(minute: float):
    return MONDAY_7AM + timedelta(minutes=minute)


def _cross(tracker, lat, minute):
    """Drive north through `lat` at 07:mm."""
    out = []
    for dt, la in ((-0.25, lat - 0.0006), (0, lat)):
        t = _at(minute + dt)
        out += tracker.update(pos(la, at=t, speed_mps=5, course=0), t)
    return out


def _tick(tracker, start, end):
    out = []
    m = start
    while m <= end:
        out += tracker.tick(_at(m))
        m += 1
    return out


def test_late_replay_no_false_alarm():
    """Measured leads 18/7.2/3.8, expected 07:30 (+15): on time, arrives, drives off."""
    tracker = _late_tracker(tolerance=15)
    tracker.lead_minutes = {"10 min": 18.0, "5 min": 7.2, "2 min": 3.8}
    alerts = []
    alerts += _tick(tracker, 1, 11)
    alerts += _cross(tracker, 39.980, 12)
    alerts += _tick(tracker, 13, 21)
    alerts += _cross(tracker, 39.990, 22)
    alerts += _cross(tracker, 39.996, 26)
    alerts += _cross(tracker, STOP_LAT, 30)
    for i, lat in enumerate([STOP_LAT + 0.004, STOP_LAT + 0.006]):  # drives off
        alerts += tracker.update(pos(lat, at=_at(36 + i), speed_mps=8, course=0), _at(36 + i))
    alerts += _tick(tracker, 31, 60)
    assert [a.kind for a in alerts] == ["checkpoint", "checkpoint", "checkpoint", "arrived"]


def test_late_reroute_skipping_a_checkpoint_is_not_late():
    tracker = _late_tracker()
    alerts = _tick(tracker, 1, 23)
    alerts += _cross(tracker, 39.990, 24)  # never passed "10 min", but reached "5 min"
    alerts += _tick(tracker, 25, 26)
    alerts += _cross(tracker, 39.996, 27)
    alerts += _tick(tracker, 28, 29)
    alerts += _cross(tracker, STOP_LAT, 30)
    assert [a.kind for a in alerts] == ["checkpoint", "checkpoint", "arrived"]


def test_late_bus_20_minutes_behind_alerts_once_about_first_checkpoint():
    tracker = _late_tracker()
    alerts = _tick(tracker, 1, 50)  # never shows up near the route
    assert len(alerts) == 1
    late = alerts[0]
    assert late.kind == "late" and late.time == _at(30)  # due 07:20 + 10
    assert late.extra["checkpoint"] == "10 min" and late.extra["minutes_late"] == 10


def test_late_stuck_between_checkpoints_names_the_next_one():
    tracker = _late_tracker()
    alerts = _tick(tracker, 1, 18)
    alerts += _cross(tracker, 39.980, 19)
    alerts += _tick(tracker, 20, 50)
    late = [a for a in alerts if a.kind == "late"]
    assert len(late) == 1 and late[0].extra["checkpoint"] == "5 min" and late[0].time == _at(35)


def test_late_uses_measured_lead_when_available():
    tracker = _late_tracker()
    tracker.lead_minutes = {"10 min": 18.0}  # really 18 min out: due 07:12, alert 07:22
    late = [a for a in _tick(tracker, 1, 40) if a.kind == "late"]
    assert late[0].time == _at(22) and late[0].extra["due"].endswith("07:12+00:00")


def test_late_restart_after_deadlines_stays_quiet():
    stop = StopConfig(STOP_LAT, STOP_LON, 75, expected_arrival=time(7, 30), late_grace_min=10)
    tracker = TripTracker(make_config(stop=stop))
    tracker.update(pos(39.95, at=_at(45), speed_mps=5, course=0), _at(45))  # HA came up 07:45
    assert _tick(tracker, 45, 70) == []


def test_late_without_checkpoints_falls_back_to_the_stop():
    tracker = _late_tracker(checkpoints=())
    late = _tick(tracker, 1, 50)
    assert [(a.kind, a.extra["stage"], a.time) for a in late] == [("late", "stop", _at(40))]
