from datetime import timedelta

from custom_components.bus_monitor.alerts import TripTracker
from custom_components.bus_monitor.calibration import (
    TrailRecorder,
    TripRecord,
    checkpoint_stats,
    position_at,
    suggest_checkpoints,
)

from .conftest import MONDAY_7AM, make_config, northbound_trail


def record_day(recorder, day_offset: int, speed_scale: float = 1.0):
    """Drive a full trip, `speed_scale` > 1 means a slower bus."""
    tracker = TripTracker(make_config())
    shift = timedelta(days=day_offset)
    for i, p in enumerate(northbound_trail()):
        when = MONDAY_7AM + shift + timedelta(seconds=15 * i * speed_scale)
        p = type(p)(p.device_id, p.lat, p.lon, when, p.speed_mps, p.course)
        for a in tracker.update(p, when):
            recorder.add_point("am", p)
            if a.kind == "arrived":
                return recorder.finish(
                    "am", when.date().isoformat(), tracker.arrival_time, tracker.crossings
                )
        recorder.add_point("am", p)


def test_stats_and_suggestions_converge():
    rec = TrailRecorder()
    for day in (0, 1, 2, 3):
        assert record_day(rec, day) is not None
    trips = rec.trips_for("am")
    stats = checkpoint_stats(trips, "10 min")
    # 10 min checkpoint is 0.020 deg (~2.2 km) from the stop at ~3.7 m/s => ~10 min
    assert stats["count"] == 4
    assert 8 < stats["median"] < 11
    suggestions = suggest_checkpoints(trips, [10, 5, 2])
    assert [s["minutes"] for s in suggestions] == [10, 5, 2]
    ten = next(s for s in suggestions if s["minutes"] == 10)
    assert abs(ten["lat"] - 39.980) < 0.004  # near the configured 10 min checkpoint
    assert ten["spread_m"] < 5


def test_slower_days_shift_baseline():
    rec = TrailRecorder()
    record_day(rec, 0)
    record_day(rec, 1, speed_scale=2.0)
    stats = checkpoint_stats(rec.trips_for("am"), "10 min")
    assert stats["p90"] > stats["p10"] * 1.5


def test_roundtrip_serialization():
    rec = TrailRecorder()
    record_day(rec, 0)
    clone = TrailRecorder.from_dict(rec.as_dict())
    assert isinstance(clone.trips[0], TripRecord)
    assert clone.trips[0].crossings == rec.trips[0].crossings


def test_one_trip_per_day_and_position_at_bounds():
    rec = TrailRecorder()
    record_day(rec, 0)
    record_day(rec, 0)
    assert len(rec.trips) == 1
    trail = rec.trips[0].trail
    assert position_at(trail, trail[0][0] - timedelta(seconds=1)) is None
    assert position_at(trail, trail[0][0]) is not None


def test_stats_none_without_data():
    assert checkpoint_stats([], "10 min") is None
    assert suggest_checkpoints([], [10]) == []


def test_stale_trail_from_an_earlier_trip_is_dropped():
    from custom_components.bus_monitor.models import Position

    rec = TrailRecorder()
    yesterday = MONDAY_7AM - timedelta(days=1)
    rec.add_point("am", Position(1, 39.9, -75.0, yesterday))
    rec.add_point("am", Position(1, 39.91, -75.0, yesterday + timedelta(seconds=30)))
    rec.add_point("am", Position(1, 39.97, -75.0, MONDAY_7AM))
    assert [p[0] for p in rec.current_trail("am")] == [MONDAY_7AM]


# --- typical_position (auto-placement) ---------------------------------------------

from custom_components.bus_monitor.calibration import typical_position  # noqa: E402
from custom_components.bus_monitor.geo import haversine_m  # noqa: E402


def _straight_trip(day: int, seconds_per_step: float = 15, detour: bool = False):
    """North along lon -75 from 39.97 to 40.0 in 0.0005 deg steps; arrival at the end."""
    t0 = MONDAY_7AM + timedelta(days=day)
    trail = []
    for i in range(61):
        lat = 39.970 + i * 0.0005
        lon = -74.996 if detour and 20 <= i <= 30 else -75.0  # ~340 m east for a while
        trail.append((t0 + timedelta(seconds=seconds_per_step * i), lat, lon, 5.0))
    return TripRecord("am", (t0.date()).isoformat(), trail[-1][0], {}, trail)


def test_typical_position_on_route_with_consistent_trips():
    trips = [_straight_trip(d) for d in range(6)]
    p = typical_position(trips, 5, min_trips=5)
    # 5 min = 20 steps before arrival => lat 40.0 - 20*0.0005 = 39.990
    assert abs(p["lat"] - 39.990) < 0.0002 and abs(p["lon"] + 75.0) < 1e-6
    assert p["trips"] == 6  # all agree


def test_typical_position_ignores_a_few_late_running_trips():
    normal = [_straight_trip(d) for d in range(6)]
    slow = [_straight_trip(10 + d, seconds_per_step=30) for d in range(2)]  # crawling: twice as slow
    base = typical_position(normal, 5, min_trips=5)
    mixed = typical_position(normal + slow, 5, min_trips=5)
    assert haversine_m(base["lat"], base["lon"], mixed["lat"], mixed["lon"]) < 30
    assert mixed["trips"] == 6  # the two slow days were left out


def test_typical_position_stays_on_the_usual_road_despite_a_detour():
    trips = [_straight_trip(d) for d in range(6)] + [_straight_trip(9, detour=True)]
    p = typical_position(trips, 5, min_trips=5)
    assert abs(p["lon"] + 75.0) < 1e-6  # not pulled east


def test_typical_position_needs_enough_trips():
    trips = [_straight_trip(d) for d in range(4)]
    assert typical_position(trips, 5, min_trips=5) is None
    assert typical_position(trips, 5) is not None  # clocks show from the first trip
