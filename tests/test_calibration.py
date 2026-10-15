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
